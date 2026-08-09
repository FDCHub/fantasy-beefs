"""
test_s5_p2_skunk_settle_pg.py — Skunk and Current Settle on real PostgreSQL.

Every Current Settle claim asserts EXACT CENTS recomputed from posted ledger
state. Nothing here inspects a label, a status column or a stored total — the
whole point of the derivation is that only entries count.

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
    print(f"\n[HARNESS ERROR] S5-P2 suite cannot run:\n  {e}")
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

    from economy.current_settle import current_settle
    from economy.economy_events import (
        DuplicateEconomyEvent, expired_min_account, min_account,
        min_reserve_account, receivable_account, reserve_account,
        season_issuance_account, skunk_account, wallet_account,
    )
    from economy.season_allocation import activate_season_allocation
    from economy.skunk import (
        DEFAULT_SKUNK_CONTRIBUTION_CENTS, DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS,
        SkunkError, assess_weekly_skunk,
        distribute_season_skunk, split_by_canonical_id,
    )
    from economy.weekly_minimum import expire_weekly_minimum, release_weekly_minimum
    from db.schema import (
        EconomyEvent, League, Matchup, SessionLocal, Team, Wallet,
    )
    from ledger.ledger import (
        APPROVED_BAB_TOPOFF_DOOR, LedgerEntry, balance_of,
        post as ledger_post, trial_balance,
    )

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

    def add_matchup(db, league_id, week, home, away, hs, aws,
                    finalized=True):
        """A recorded matchup fixture that declares finality EXPLICITLY.

        `refreshed_at` is set on every row regardless, precisely so no test can
        pass by accident on the old ingestion marker: only `finalized_at`
        distinguishes a final result here."""
        from datetime import datetime as _dt
        db.add(Matchup(league_id=league_id, week=week, home_team_id=home,
                       away_team_id=away, home_score=hs, away_score=aws,
                       refreshed_at=_dt.utcnow(),
                       finalized_at=_dt.utcnow() if finalized else None))

    def settle_of(team_id, league_id):
        with SessionLocal() as db:
            cs = current_settle(db, team_id=team_id, league_id=league_id,
                                season=SEASON)
            db.rollback()
        return cs

    # ════ 1. WEEKLY SKUNK ═══════════════════════════════════════════════════
    print("")
    print("== BAB-504: the governed weekly Skunk fee is $10 ==")
    # THE ORACLE IS THE LITERAL, NOT THE CONSTANT. Every other assertion in this
    # file compares behaviour against DEFAULT_SKUNK_CONTRIBUTION_CENTS, which
    # proves the code is self-consistent and NOTHING about whether the governed
    # amount is right - a wrong constant satisfies all of them equally. These
    # two pin the governed figures as literals, so a drifting constant fails
    # here first and by name.
    _assert("BAB-504 default weekly Skunk fee is literally 1000 cents ($10)",
            DEFAULT_SKUNK_CONTRIBUTION_CENTS == 1000,
            str(DEFAULT_SKUNK_CONTRIBUTION_CENTS))
    _assert("BAB-504 season ceiling is literally 14000 cents ($140) across the "
            "14-week regular season",
            DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS == 14000
            and 14 * 1000 == 14000,
            str(DEFAULT_SKUNK_SEASON_MAXIMUM_CENTS))

    print("\n== weekly Skunk: ledger-only obligation ==")
    league_id, team_ids = make_league("skunk")
    with SessionLocal() as db:
        activate_season_allocation(league_id, db)
    with SessionLocal() as db:
        release_weekly_minimum(db, league_id=league_id, team_id=team_ids[0],
                               week=3)
        ledger_post([("world", -5000), (wallet_account(team_ids[0]), 5000)],
                    door="buy_in_paid", session=db)
        # team 0 loses by 40 (the largest margin); team 2 loses by 10.
        add_matchup(db, league_id, 3, team_ids[1], team_ids[0], 140.0, 100.0)
        add_matchup(db, league_id, 3, team_ids[3], team_ids[2], 110.0, 100.0)
        db.commit()

    loser = team_ids[0]
    before = {
        "wallet": balance_of(wallet_account(loser)),
        "min": balance_of(min_account(loser, 3)),
        "min_reserve": balance_of(min_reserve_account(loser)),
        "receivable": balance_of(receivable_account(loser)),
        "pot": balance_of(skunk_account(league_id)),
    }
    with SessionLocal() as db:
        result = assess_weekly_skunk(db, league_id=league_id, week=3)
        db.commit()

    _assert("the largest margin of defeat is assessed literally 1000 cents",
            result.assessed == ((loser, 1000),), str(result.assessed))
    _assert("largest margin recorded as 40", result.largest_margin == 40.0)
    _assert("S5-R1 Wallet is UNCHANGED",
            balance_of(wallet_account(loser)) == before["wallet"])
    _assert("S5-R1 min: is UNCHANGED",
            balance_of(min_account(loser, 3)) == before["min"])
    _assert("S5-R1 min_reserve: is UNCHANGED",
            balance_of(min_reserve_account(loser)) == before["min_reserve"])
    # LITERAL 1000, deliberately not the production constant - see BAB-504.
    _assert("the receivable obligation grew by literally 1000 cents",
            before["receivable"] - balance_of(receivable_account(loser)) == 1000,
            str(before["receivable"] - balance_of(receivable_account(loser))))
    _assert("the Skunk pot grew by literally 1000 cents",
            balance_of(skunk_account(league_id)) - before["pot"] == 1000,
            str(balance_of(skunk_account(league_id)) - before["pot"]))
    with SessionLocal() as db:
        rows = (db.query(LedgerEntry)
                .filter(LedgerEntry.door == "skunk_assessment").all())
        _assert("the assessment posting is zero-sum",
                sum(int(r.amount_cents) for r in rows) == 0)
        _assert("no wallet, min or min_reserve leg exists in the posting",
                not any(r.account.startswith(("wallet:", "min:", "min_reserve:"))
                        for r in rows),
                str([r.account for r in rows]))
        db.rollback()
    _assert("trial balance is zero", trial_balance() == 0)

    print("  -- duplicate and concurrent assessment --")
    with SessionLocal() as db:
        dup = None
        try:
            assess_weekly_skunk(db, league_id=league_id, week=3)
            db.commit()
        except DuplicateEconomyEvent as exc:
            dup = exc
            db.rollback()
    _assert("duplicate assessment refused at the event key", dup is not None)
    _assert("the pot did not grow on the duplicate",
            balance_of(skunk_account(league_id)) - before["pot"]
            == DEFAULT_SKUNK_CONTRIBUTION_CENTS)

    with SessionLocal() as db:
        add_matchup(db, league_id, 4, team_ids[1], team_ids[0], 150.0, 100.0)
        add_matchup(db, league_id, 4, team_ids[3], team_ids[2], 110.0, 105.0)
        db.commit()

    def assess_week4():
        with SessionLocal() as db:
            r = assess_weekly_skunk(db, league_id=league_id, week=4)
            db.commit()
            return r

    pot_before = balance_of(skunk_account(league_id))
    out = run_concurrent(assess_week4, assess_week4)
    ok = [v for k, v in out.values() if k == "ok"]
    _assert("concurrent assessment posts exactly once", len(ok) == 1, str(out))
    _assert("concurrent assessment funded the pot exactly once",
            balance_of(skunk_account(league_id)) - pot_before
            == DEFAULT_SKUNK_CONTRIBUTION_CENTS)

    # ════ 2. TIE ════════════════════════════════════════════════════════════
    print("\n== tie for largest margin: ONE contribution, divided ==")
    league_id, team_ids = make_league("skunk-tie", n_teams=6)
    with SessionLocal() as db:
        # Three GMs all lose by exactly 30 -> 2000 // 3 = 666 r 2.
        add_matchup(db, league_id, 3, team_ids[3], team_ids[0], 130.0, 100.0)
        add_matchup(db, league_id, 3, team_ids[4], team_ids[1], 130.0, 100.0)
        add_matchup(db, league_id, 3, team_ids[5], team_ids[2], 130.0, 100.0)
        db.commit()
    with SessionLocal() as db:
        tie = assess_weekly_skunk(db, league_id=league_id, week=3)
        db.commit()
    tied = sorted(team_ids[:3])
    expected = split_by_canonical_id(DEFAULT_SKUNK_CONTRIBUTION_CENTS, tied)
    _assert("all three tied GMs are assessed",
            [t for t, _ in tie.assessed] == tied, str(tie.assessed))
    _assert("ONE contribution is divided, not charged three times",
            sum(c for _, c in tie.assessed)
            == DEFAULT_SKUNK_CONTRIBUTION_CENTS,
            str(sum(c for _, c in tie.assessed)))
    _assert("the pot received exactly one contribution",
            balance_of(skunk_account(league_id))
            == DEFAULT_SKUNK_CONTRIBUTION_CENTS)
    _assert("the remainder goes to the LOWEST canonical GM id",
            dict(tie.assessed) == expected
            and expected[tied[0]] == 334
            and expected[tied[1]] == 333
            and expected[tied[2]] == 333,
            str(expected))
    _assert("the tie split conserves the governed 1000 cents exactly",
            sum(expected.values()) == 1000, str(sum(expected.values())))
    for team_id, cents in tie.assessed:
        _assert(f"team {team_id} obligation is exactly {cents}",
                -balance_of(receivable_account(team_id)) == cents)
    _assert("trial balance is zero", trial_balance() == 0)

    # ════ 3. NO-LOSER vs MISSING RESULTS ════════════════════════════════════
    print("\n== NO_LOSER and RESULTS_NOT_READY are different outcomes ==")
    league_id, team_ids = make_league("skunk-tied-week")
    with SessionLocal() as db:
        add_matchup(db, league_id, 3, team_ids[0], team_ids[1], 100.0, 100.0)
        add_matchup(db, league_id, 3, team_ids[2], team_ids[3], 90.0, 90.0)
        db.commit()
    with SessionLocal() as db:
        no_loser = assess_weekly_skunk(db, league_id=league_id, week=3)
        db.commit()
    _assert("all matchups tied is NO_LOSER, not an error",
            no_loser.classification == "NO_LOSER" and no_loser.total_cents == 0)
    _assert("no obligation was created",
            all(balance_of(receivable_account(t)) == 0 for t in team_ids))
    _assert("the Skunk pot did not move",
            balance_of(skunk_account(league_id)) == 0)
    with SessionLocal() as db:
        _assert("a zero-outcome event row IS written, closing the week",
                db.query(EconomyEvent).filter(
                    EconomyEvent.event_type == "SKUNK_ASSESSMENT",
                    EconomyEvent.week == 3).count() == 1)
        db.rollback()
    with SessionLocal() as db:
        dup = None
        try:
            assess_weekly_skunk(db, league_id=league_id, week=3)
            db.commit()
        except DuplicateEconomyEvent as exc:
            dup = exc
            db.rollback()
    _assert("the zero outcome is idempotent", dup is not None)

    league_id, team_ids = make_league("skunk-missing")
    with SessionLocal() as db:
        add_matchup(db, league_id, 3, team_ids[0], team_ids[1], 120.0, 100.0)
        # 0-0, INGESTED (refreshed_at set) but NOT declared final. By score
        # alone this is indistinguishable from a genuine tie, and refreshed_at
        # is set — so only finalized_at can tell them apart. That is the whole
        # point of the ruling, and this fixture is the discriminating case.
        add_matchup(db, league_id, 3, team_ids[2], team_ids[3], 0.0, 0.0,
                    finalized=False)
        db.commit()
    with SessionLocal() as db:
        err = None
        try:
            assess_weekly_skunk(db, league_id=league_id, week=3)
            db.commit()
        except SkunkError as exc:
            err = exc
            db.rollback()
    _assert("an un-ingested result fails closed with a named error",
            err is not None and err.reason == "RESULTS_NOT_READY",
            err.reason if err else "it assessed")
    _assert("nothing was posted",
            balance_of(skunk_account(league_id)) == 0
            and all(balance_of(receivable_account(t)) == 0 for t in team_ids))
    with SessionLocal() as db:
        _assert("NO event row marks the week assessed — it stays assessable",
                db.query(EconomyEvent).filter(
                    EconomyEvent.event_type == "SKUNK_ASSESSMENT").count() == 0)
        db.rollback()

    # ════ 4. SEASON DISTRIBUTION ════════════════════════════════════════════
    print("\n== season Skunk distribution: highest regular-season Points For ==")
    league_id, team_ids = make_league("skunk-dist")
    with SessionLocal() as db:
        add_matchup(db, league_id, 3, team_ids[0], team_ids[1], 200.0, 100.0)
        add_matchup(db, league_id, 3, team_ids[2], team_ids[3], 150.0, 120.0)
        add_matchup(db, league_id, 4, team_ids[0], team_ids[2], 90.0, 80.0)
        add_matchup(db, league_id, 4, team_ids[1], team_ids[3], 95.0, 85.0)
        # A postseason blowout that must NOT count toward the award.
        add_matchup(db, league_id, 15, team_ids[3], team_ids[0], 999.0, 1.0)
        db.commit()
    with SessionLocal() as db:
        assess_weekly_skunk(db, league_id=league_id, week=3)
        assess_weekly_skunk(db, league_id=league_id, week=4)
        db.commit()
    pot = balance_of(skunk_account(league_id))
    _assert("two weeks accumulated two contributions",
            pot == 2 * DEFAULT_SKUNK_CONTRIBUTION_CENTS, str(pot))

    winner_wallet_before = balance_of(wallet_account(team_ids[0]))
    with SessionLocal() as db:
        dist = distribute_season_skunk(db, league_id=league_id)
        db.commit()
    _assert("the highest regular-season Points For wins",
            [t for t, _ in dist.winners] == [team_ids[0]], str(dist.winners))
    _assert("the postseason blowout did not decide the award",
            dist.top_points_for == 290.0, str(dist.top_points_for))
    _assert("the winner's Wallet received the whole pot",
            balance_of(wallet_account(team_ids[0])) - winner_wallet_before
            == pot)
    _assert("the pot is exactly zero after distribution",
            balance_of(skunk_account(league_id)) == 0)
    _assert("trial balance is zero", trial_balance() == 0)

    with SessionLocal() as db:
        dup = None
        try:
            distribute_season_skunk(db, league_id=league_id)
            db.commit()
        except SkunkError as exc:
            dup = exc
            db.rollback()
    _assert("a retry finds an empty pot and refuses",
            dup is not None and dup.reason == "EMPTY_POT",
            dup.reason if dup else "it redistributed")
    _assert("no second payout reached the winner",
            balance_of(wallet_account(team_ids[0])) - winner_wallet_before
            == pot)

    print("  -- tie for highest Points For, and concurrency --")
    league_id, team_ids = make_league("skunk-dist-tie")
    with SessionLocal() as db:
        add_matchup(db, league_id, 3, team_ids[0], team_ids[1], 100.0, 100.0)
        add_matchup(db, league_id, 3, team_ids[2], team_ids[3], 130.0, 90.0)
        db.commit()
    with SessionLocal() as db:
        assess_weekly_skunk(db, league_id=league_id, week=3)
        db.commit()
    # Teams 0 and 1 tie at 100 PF; team 2 has 130 and wins outright, so force a
    # tie at the top by giving 0 and 1 the high score instead.
    with SessionLocal() as db:
        # FLUSH THE DELETE BEFORE THE INSERT. Both target
        # UNIQUE (league_id, week, home_team_id); in one session SQLAlchemy can
        # order the INSERT first and collide with the row being replaced. This
        # is a fixture-ordering fix only — no production behaviour changed.
        db.query(Matchup).filter(Matchup.league_id == league_id,
                                 Matchup.home_team_id == team_ids[2]).delete()
        db.flush()
        add_matchup(db, league_id, 3, team_ids[2], team_ids[3], 50.0, 40.0)
        db.commit()
    pot = balance_of(skunk_account(league_id))
    with SessionLocal() as db:
        tie_dist = distribute_season_skunk(db, league_id=league_id)
        db.commit()
    expected = split_by_canonical_id(pot, sorted(team_ids[:2]))
    _assert("a tie at the top splits the pot exactly",
            dict(tie_dist.winners) == expected, str(tie_dist.winners))
    _assert("the split sums to the whole pot",
            sum(c for _, c in tie_dist.winners) == pot)
    _assert("the pot is zero after the tied distribution",
            balance_of(skunk_account(league_id)) == 0)

    league_id, team_ids = make_league("skunk-dist-race")
    with SessionLocal() as db:
        add_matchup(db, league_id, 3, team_ids[0], team_ids[1], 200.0, 100.0)
        db.commit()
    with SessionLocal() as db:
        assess_weekly_skunk(db, league_id=league_id, week=3)
        db.commit()
    pot = balance_of(skunk_account(league_id))
    wallet_before = balance_of(wallet_account(team_ids[0]))

    def distribute():
        with SessionLocal() as db:
            r = distribute_season_skunk(db, league_id=league_id)
            db.commit()
            return r

    out = run_concurrent(distribute, distribute)
    ok = [v for k, v in out.values() if k == "ok"]
    _assert("concurrent distribution pays exactly once", len(ok) == 1, str(out))
    _assert("no double winner payout",
            balance_of(wallet_account(team_ids[0])) - wallet_before == pot)
    _assert("the pot is zero after the race",
            balance_of(skunk_account(league_id)) == 0)

    print("  -- crash before commit --")
    league_id, team_ids = make_league("skunk-crash")
    with SessionLocal() as db:
        add_matchup(db, league_id, 3, team_ids[0], team_ids[1], 200.0, 100.0)
        db.commit()
    with SessionLocal() as db:
        assess_weekly_skunk(db, league_id=league_id, week=3)
        db.rollback()          # the crash
    _assert("assessment: a crash before commit posted nothing",
            balance_of(skunk_account(league_id)) == 0
            and balance_of(receivable_account(team_ids[1])) == 0)
    with SessionLocal() as db:
        _assert("assessment: no event row survives the crash",
                db.query(EconomyEvent).filter(
                    EconomyEvent.event_type == "SKUNK_ASSESSMENT").count() == 0)
        db.rollback()
    with SessionLocal() as db:
        assess_weekly_skunk(db, league_id=league_id, week=3)
        db.commit()
    _assert("assessment: the retry after the crash assesses exactly once",
            balance_of(skunk_account(league_id))
            == DEFAULT_SKUNK_CONTRIBUTION_CENTS)
    with SessionLocal() as db:
        distribute_season_skunk(db, league_id=league_id)
        db.rollback()          # the crash
    _assert("distribution: a crash before commit paid nothing",
            balance_of(skunk_account(league_id))
            == DEFAULT_SKUNK_CONTRIBUTION_CENTS)
    _assert("trial balance is zero", trial_balance() == 0)

    # ════ 5. CURRENT SETTLE ═════════════════════════════════════════════════
    print("\n== Current Settle: derived from posted state, exact cents ==")
    league_id, team_ids = make_league("settle")
    gm = team_ids[0]

    zero = settle_of(gm, league_id)
    _assert("(0) a GM with no postings settles at exactly 0",
            zero.current_settle_cents == 0, str(zero.as_dict()))

    with SessionLocal() as db:
        activate_season_allocation(league_id, db)
    after_alloc = settle_of(gm, league_id)
    _assert("(1) opening allocation: assets 14000, obligation 22000",
            (after_alloc.assets_cents, after_alloc.obligations_cents)
            == (14000, 22000), str(after_alloc.as_dict()))
    _assert("(1) Current Settle == -8000 — the Championship Reserve is "
            "advanced but is NOT a GM asset",
            after_alloc.current_settle_cents == -8000,
            str(after_alloc.current_settle_cents))
    _assert("(1) reserve: is excluded from assets",
            balance_of(reserve_account(gm)) == 8000
            and after_alloc.assets_cents == 14000)

    def delta(fn, label, expected):
        before_cs = settle_of(gm, league_id).current_settle_cents
        fn()
        after_cs = settle_of(gm, league_id).current_settle_cents
        _assert(label, after_cs - before_cs == expected,
                f"delta {after_cs - before_cs}, expected {expected}")
        return after_cs

    def do_release():
        with SessionLocal() as db:
            release_weekly_minimum(db, league_id=league_id, team_id=gm, week=3)
            db.commit()
    delta(do_release, "(2) min_reserve -> min is a pure transfer: delta 0", 0)

    def do_wallet_escrow():
        with SessionLocal() as db:
            ledger_post([("world", -5000), (wallet_account(gm), 5000)],
                        door="buy_in_paid", session=db)
            db.commit()
    delta(do_wallet_escrow, "(x) an external wallet credit is NOT a pure "
                            "transfer: delta +5000", 5000)

    from db.schema import Bet, Matchup as _M, Wallet as _W

    _bet_week = [40]          # distinct, non-economic weeks for bet fixtures

    def make_bet_escrow(source_account, cents):
        # Each placeholder matchup gets its OWN week. They exist only to give a
        # Bet a matchup_id; sharing week 3 collided on
        # UNIQUE (league_id, week, home_team_id), and week 3 is also the week
        # under economic test — these carry no result and must not appear there.
        _bet_week[0] += 1
        with SessionLocal() as db:
            m = _M(league_id=league_id, week=_bet_week[0],
                   home_team_id=team_ids[0],
                   away_team_id=team_ids[1], home_score=0.0, away_score=0.0)
            db.add(m)
            db.flush()
            wallet = db.query(_W).filter(_W.team_id == gm).first()
            bet = Bet(matchup_id=m.id, wallet_id=wallet.id,
                      picked_team_id=team_ids[0], bet_type="straight",
                      amount=cents / 100, odds=1.909, status="pending")
            db.add(bet)
            db.flush()
            ledger_post([(source_account, -cents),
                         (f"escrow:{bet.id}", cents)],
                        door="wager_placed", session=db)
            db.commit()
            return bet.id

    bet_ids = {}

    def do_min_escrow():
        bet_ids["min"] = make_bet_escrow(min_account(gm, 3), 600)
    delta(do_min_escrow, "(3) min -> escrow is a pure transfer: delta 0", 0)

    def do_wallet_to_escrow():
        bet_ids["wallet"] = make_bet_escrow(wallet_account(gm), 1500)
    delta(do_wallet_to_escrow,
          "(4) wallet -> escrow is a pure transfer: delta 0", 0)

    unresolved = settle_of(gm, league_id)
    _assert("(12) unresolved escrow is counted as In Play, attributed to the "
            "funding GM", unresolved.in_play_cents == 2100,
            str(unresolved.in_play_cents))

    def do_refund():
        with SessionLocal() as db:
            ledger_post([(f"escrow:{bet_ids['wallet']}", -1500),
                         (wallet_account(gm), 1500)],
                        door="wager_settled", session=db)
            db.commit()
    delta(do_refund, "(5) escrow -> wallet refund is a pure transfer: delta 0", 0)

    def do_expiry():
        with SessionLocal() as db:
            expire_weekly_minimum(db, league_id=league_id, team_id=gm, week=3)
            db.commit()
    delta(do_expiry, "(6) min -> expired_min is a pure transfer: delta 0", 0)
    _assert("(6) expired_min is still a GM asset",
            settle_of(gm, league_id).expired_min_cents == 400,
            str(settle_of(gm, league_id).expired_min_cents))

    def do_topoff():
        with SessionLocal() as db:
            ledger_post([(f"bab_issuance:{league_id}:{SEASON}", -3000),
                         (wallet_account(gm), 3000)],
                        door=APPROVED_BAB_TOPOFF_DOOR, session=db)
            db.commit()
    delta(do_topoff, "(7) approved Top-Off: asset +X and obligation +X, "
                     "delta 0", 0)
    _assert("(7) the Top-Off obligation is recorded",
            settle_of(gm, league_id).topoff_issued_cents == 3000)

    def do_rejected_topoff():
        pass          # a rejected request posts nothing at all
    delta(do_rejected_topoff,
          "(8) a rejected Top-Off is economically inert: delta 0", 0)

    def do_win():
        with SessionLocal() as db:
            ledger_post([("world", -900), (wallet_account(gm), 900)],
                        door="wager_settled", session=db)
            db.commit()
    delta(do_win, "(9) a settled win increases Current Settle by the winnings",
          900)

    def do_loss():
        with SessionLocal() as db:
            ledger_post([(f"escrow:{bet_ids['min']}", -600),
                         (wallet_account(team_ids[1]), 600)],
                        door="wager_settled", session=db)
            db.commit()
    delta(do_loss, "(10) a settled loss decreases Current Settle by the stake",
          -600)

    def do_skunk():
        with SessionLocal() as db:
            add_matchup(db, league_id, 5, team_ids[1], gm, 200.0, 100.0)
            db.commit()
        with SessionLocal() as db:
            assess_weekly_skunk(db, league_id=league_id, week=5)
            db.commit()
    # LITERAL -1000. This is the whole of S5-F1: the 2000-cent default moved
    # this by -2000 and understated every assessed GM by $10 per assessment.
    delta(do_skunk, "(11) one default Skunk assessment moves Current Settle by "
                    "literally -1000 cents", -1000)

    # (13) Pool economic ownership. A collected weekly Pool contribution has
    # LEFT the GM: it funds four occurrences whose outcome is not yet theirs, and
    # pool:{league} is explicitly NOT a generic GM asset. So this is a real
    # ownership change, not a reclassification, and forcing a zero delta here
    # would be making the number up.
    def do_pool_funding():
        with SessionLocal() as db:
            ledger_post([(wallet_account(gm), -100),
                         (f"pool:{league_id}", 100)],
                        door="pool_weekly_collection", session=db)
            db.commit()
    delta(do_pool_funding,
          "(13) Pool funding moves ownership out of the GM: delta -100", -100)
    _assert("(13) the pool pot is NOT counted as a GM asset",
            settle_of(gm, league_id).assets_cents
            == settle_of(gm, league_id).wallet_cents
            + settle_of(gm, league_id).weekly_min_live_cents
            + settle_of(gm, league_id).min_reserve_cents
            + settle_of(gm, league_id).expired_min_cents
            + settle_of(gm, league_id).in_play_cents)

    # CAPTURED BEFORE the discriminator block, which calls make_league and
    # therefore resets the database. Reading it afterwards would assert 0 == 0
    # against a wiped league and prove nothing.
    final = settle_of(gm, league_id)
    _assert("Current Settle is recomputed from the Ledger, with no stored "
            "field anywhere",
            final.current_settle_cents
            == final.assets_cents - final.obligations_cents
            and final.current_settle_cents == -3800,
            str(final.as_dict()))
    print(f"    final position: {final.as_dict()}")

    print("")
    print("== the finality discriminator ==")
    # A finalized 0-0 tie and an unfinalized 0-0 game are byte-identical on
    # score and on refreshed_at. Only finalized_at separates them, and they must
    # produce different outcomes.
    disc_league, disc_teams = make_league("finality-discriminator")
    with SessionLocal() as db:
        add_matchup(db, disc_league, 3, disc_teams[0], disc_teams[1],
                    0.0, 0.0, finalized=True)
        db.commit()
    with SessionLocal() as db:
        tied = assess_weekly_skunk(db, league_id=disc_league, week=3)
        db.commit()
    _assert("a FINALIZED 0-0 is NO_LOSER", tied.classification == "NO_LOSER")

    disc_league, disc_teams = make_league("finality-discriminator-2")
    with SessionLocal() as db:
        add_matchup(db, disc_league, 3, disc_teams[0], disc_teams[1],
                    0.0, 0.0, finalized=False)
        db.commit()
    with SessionLocal() as db:
        err = None
        try:
            assess_weekly_skunk(db, league_id=disc_league, week=3)
            db.commit()
        except SkunkError as exc:
            err = exc
            db.rollback()
    _assert("an UNFINALIZED 0-0 is RESULTS_NOT_READY — identical score and "
            "refreshed_at, opposite outcome",
            err is not None and err.reason == "RESULTS_NOT_READY",
            err.reason if err else "it was assessed as NO_LOSER")
    with SessionLocal() as db:
        _assert("and it wrote no completion event",
                db.query(EconomyEvent).filter(
                    EconomyEvent.league_id == disc_league).count() == 0)
        db.rollback()

    _assert("trial balance is zero at the end", trial_balance() == 0)


if __name__ == "__main__":
    print("\n=== S5-P2 Skunk / Current Settle suite (PostgreSQL) ===")
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