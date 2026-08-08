"""
test_fr87_6d1_post_claim_pre_lock_crash_pg.py — FR-8.7 test 6d-1 (PostgreSQL).

SCENARIO (FR_8_7_TEST_6D_SPEC_FROZEN, 6d-1 — post-claim / pre-lock crash).
A settle_week process dies AFTER the Phase-1 claim commit and BEFORE the Phase-2
`SELECT ... FOR UPDATE`. The claim is durable; no Phase-2 query ever executed.
Nothing economic may have happened, and no ordinary caller may settle the week
afterwards.

LINE ANCHORS. Re-verified at HEAD f230d33. The frozen spec's anchors were taken
at 21ec171 and have drifted:

    Phase-1 claim commit          spec 360  ->  362
    CLAIMED-no-token guard        spec 394  ->  396
    that guard's ValueError       spec 395  ->  397
    SELECT ... FOR UPDATE         spec 435  ->  437 (FOR UPDATE keyword at 441)

On the winning-claimant path execution runs 362 -> 437 with only a function
definition between them; the conflict block at 364-420 never executes for the
claimant. That is the injection window.

CRASH INJECTION IS A REAL PROCESS DEATH. test_support_crash spawns a child that
calls settle_week and dies via os._exit() at PRE_LOCK — no unwinding, no session
cleanup, no atexit. A caught exception in-process would prove nothing about
durability across process death.

WHY A BEEF PAIR AND NOT A STRAIGHT BET. Single-party bets never touch the
ledger: settlement mutates Wallet.balance directly and inserts a Transaction.
Only beef bets post to the ledger, draining escrow:{bet_id} into
wallet:{team_id} under door "wager_settled". Seeded with a straight bet, this
suite's escrow and wager_settled assertions would be vacuous — there would be no
escrow that settlement was ever going to drain. A matched beef pair makes every
ledger assertion load-bearing.

The seed is still light. 6d-1 crashes BEFORE the payout loop, so _eval_beef
never runs: no BeefStarter rows, no proposals, no scores are required. The
challenge row, two pending bets, and escrow funded through the real doors
(buy_in_paid then wager_placed) are sufficient and honest.

ASSERTIONS (19). Covers all six spec fields for 6d-1: durable state, recovery
authority, token behavior, retry expectations, ledger invariants, and — first —
that the fixture actually crashed where it claimed to.

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Harness FIRST — setup_postgres_test_db() applies its guards, sets DATABASE_URL
# to the disposable test DB, and imports+binds db.schema INTERNALLY. No project
# module may be imported before this call.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] FR-8.7 6d-1 suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection begins
    the instant setup succeeds."""
    from datetime import datetime, timedelta, timezone

    from db.schema import (
        SessionLocal,
        League, Team, Matchup, NflSchedule, Wallet, Bet, Transaction,
        BeefChallenge, WeekSettlement, SettlementRecoveryAudit,
    )
    from ledger.ledger import post as ledger_post, balance_of, trial_balance, LedgerEntry
    from betting.settlement_engine import settle_week
    from betting.per_bet_lock import LOCK_SEASON
    from config import CURRENT_SEASON as SEASON

    # test_support_crash imports nothing from the project at module level, so it
    # is safe here (and would be safe at module top).
    from test_support_crash import (
        run_settle_week_crashing, assert_crashed, PRE_LOCK,
    )

    FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)
    _WEEK = 1

    # Stakes deliberately UNEQUAL. Equal stakes would let a symmetric-assumption
    # bug pass; the money path must reconcile to ACTUAL escrow.
    STAKE_A = 25.00
    STAKE_B = 40.00
    STAKE_A_CENTS = int(round(STAKE_A * 100))
    STAKE_B_CENTS = int(round(STAKE_B * 100))

    # Wallet ledger funding — comfortably above each stake so the funded-balance
    # guard (MS-L1-5.1) is satisfied by real money, not by an exemption.
    FUND_CENTS = 20_000

    # Legacy Float wallet balance, separate from the ledger account of the same
    # name. Settlement's single-party path mutates this; the beef path does not.
    # Asserted unchanged either way.
    WALLET_BALANCE_SEED = 500.00

    # ── League ────────────────────────────────────────────────────────────────
    with SessionLocal() as _db:
        league = League(season=SEASON, name="FR-8.7 6d-1 Pre-Lock Crash League",
                        projection_source="fantasypros")
        _db.add(league)
        _db.commit()
        LEAGUE_ID = league.id

    # ── Two Teams ─────────────────────────────────────────────────────────────
    with SessionLocal() as _db:
        home = Team(league_id=LEAGUE_ID, team_name="6d1 Home", owner="home6d1",
                    email="home@6d1test.com")
        away = Team(league_id=LEAGUE_ID, team_name="6d1 Away", owner="away6d1",
                    email="away@6d1test.com")
        _db.add(home)
        _db.add(away)
        _db.commit()
        HOME_ID = home.id
        AWAY_ID = away.id

    # ── Wallets (legacy Float balances) ───────────────────────────────────────
    with SessionLocal() as _db:
        wh = Wallet(team_id=HOME_ID, balance=WALLET_BALANCE_SEED)
        wa = Wallet(team_id=AWAY_ID, balance=WALLET_BALANCE_SEED)
        _db.add(wh)
        _db.add(wa)
        _db.commit()
        WALLET_HOME_ID = wh.id
        WALLET_AWAY_ID = wa.id

    # ── Matchup + NflSchedule. The pending query joins Matchup and filters on
    # (league_id, week), so the bets must hang off a matchup in this week. ─────
    with SessionLocal() as _db:
        m = Matchup(league_id=LEAGUE_ID, week=_WEEK,
                    home_team_id=HOME_ID, away_team_id=AWAY_ID,
                    home_score=0.0, away_score=0.0)
        _db.add(m)
        _db.add(NflSchedule(season=LOCK_SEASON, week=_WEEK,
                            home_team="KC", away_team="PHI",
                            kickoff_utc=FUTURE_KO))
        _db.commit()
        MATCHUP_ID = m.id

    # ── Matched beef pair. status='accepted' with both bet ids linked is the
    # shape settle_week's beef branch expects. week_settlements is NOT
    # pre-inserted — the child's own Phase-1 claim (353-362) creates it. ───────
    with SessionLocal() as _db:
        bet_a = Bet(matchup_id=MATCHUP_ID, wallet_id=WALLET_HOME_ID,
                    picked_team_id=HOME_ID, bet_type="straight",
                    amount=STAKE_A, odds=2.60, status="pending",
                    description="6d-1 beef challenger")
        bet_b = Bet(matchup_id=MATCHUP_ID, wallet_id=WALLET_AWAY_ID,
                    picked_team_id=AWAY_ID, bet_type="straight",
                    amount=STAKE_B, odds=1.625, status="pending",
                    description="6d-1 beef challenged")
        _db.add(bet_a)
        _db.add(bet_b)
        _db.commit()
        BET_A_ID = bet_a.id
        BET_B_ID = bet_b.id

    with SessionLocal() as _db:
        challenge = BeefChallenge(
            challenger_team_id   = HOME_ID,
            challenged_team_id   = AWAY_ID,
            league_id            = LEAGUE_ID,
            week                 = _WEEK,
            bet_type             = "straight",
            amount               = STAKE_A,
            challenger_odds      = 2.60,
            challenged_odds      = 1.625,
            challenger_moneyline = 160,
            challenged_moneyline = -160,
            status               = "accepted",
            challenge_mode       = "locked",
            expires_at           = datetime.now(timezone.utc) + timedelta(days=1),
            responded_at         = datetime.now(timezone.utc),
            challenger_bet_id    = BET_A_ID,
            challenged_bet_id    = BET_B_ID,
        )
        _db.add(challenge)
        _db.commit()
        CHALLENGE_ID = challenge.id

    with SessionLocal() as _db:
        _db.query(Bet).filter(Bet.id.in_([BET_A_ID, BET_B_ID])).update(
            {"beef_challenge_id": CHALLENGE_ID}, synchronize_session=False
        )
        _db.commit()

    # ── Fund the ledger through the real doors, then place both stakes into
    # escrow. "world" is exempt from the funded-balance guard by design; the
    # wallet debits below are NOT, so they are covered by real funding. ────────
    ledger_post([("world", -FUND_CENTS), (f"wallet:{HOME_ID}", FUND_CENTS)],
                door="buy_in_paid")
    ledger_post([("world", -FUND_CENTS), (f"wallet:{AWAY_ID}", FUND_CENTS)],
                door="buy_in_paid")
    ledger_post([(f"wallet:{HOME_ID}", -STAKE_A_CENTS),
                 (f"escrow:{BET_A_ID}",  STAKE_A_CENTS)],
                door="wager_placed")
    ledger_post([(f"wallet:{AWAY_ID}", -STAKE_B_CENTS),
                 (f"escrow:{BET_B_ID}",  STAKE_B_CENTS)],
                door="wager_placed")

    # Pre-crash snapshot — captured from the database, never assumed.
    escrow_a_before = balance_of(f"escrow:{BET_A_ID}")
    escrow_b_before = balance_of(f"escrow:{BET_B_ID}")
    wallet_home_ledger_before = balance_of(f"wallet:{HOME_ID}")
    wallet_away_ledger_before = balance_of(f"wallet:{AWAY_ID}")
    trial_before = trial_balance()

    print(f"  (seed) escrow:{BET_A_ID}={escrow_a_before}c  "
          f"escrow:{BET_B_ID}={escrow_b_before}c  trial={trial_before}c")

    # ── THE CRASH ─────────────────────────────────────────────────────────────
    proc = run_settle_week_crashing(_WEEK, LEAGUE_ID, PRE_LOCK)
    crashed, crash_detail = assert_crashed(proc)

    # 0. Fixture proof FIRST. Without this, a child that died from an import
    # error would leave the database untouched and every assertion below would
    # pass green while proving nothing.
    _assert(
        "0: child process crashed at PRE_LOCK (marker + exit code)",
        crashed,
        detail=crash_detail,
    )

    # ── Durable week_settlements state ────────────────────────────────────────
    with SessionLocal() as db:
        ws_rows = (
            db.query(WeekSettlement)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK)
            .all()
        )
        ws = ws_rows[0] if ws_rows else None
        ws_count = len(ws_rows)

    _assert(
        "1: exactly one week_settlements row exists (the claim is durable)",
        ws_count == 1,
        detail=f"row count={ws_count}",
    )
    _assert(
        "2: status == CLAIMED",
        ws is not None and ws.status == "CLAIMED",
        detail=f"status={getattr(ws, 'status', '<none>')!r}",
    )
    _assert(
        "3: settled is False",
        ws is not None and ws.settled is False,
        detail=f"settled={getattr(ws, 'settled', '<none>')}",
    )
    _assert(
        "4: settled_at is None",
        ws is not None and ws.settled_at is None,
        detail=f"settled_at={getattr(ws, 'settled_at', '<none>')}",
    )
    _assert(
        "5: recovery_token is None (a failed normal run mints no token)",
        ws is not None and ws.recovery_token is None,
        detail=f"recovery_token={getattr(ws, 'recovery_token', '<none>')!r}",
    )

    # ── Zero bets touched ─────────────────────────────────────────────────────
    with SessionLocal() as db:
        bets = db.query(Bet).filter(Bet.id.in_([BET_A_ID, BET_B_ID])).order_by(Bet.id).all()
        statuses = [b.status for b in bets]
        settled_ats = [b.settled_at for b in bets]

    _assert(
        "6: both bets still status == pending",
        statuses == ["pending", "pending"],
        detail=f"statuses={statuses}",
    )
    _assert(
        "7: neither bet has settled_at set",
        all(s is None for s in settled_ats),
        detail=f"settled_at={settled_ats}",
    )

    # ── Zero payouts ──────────────────────────────────────────────────────────
    with SessionLocal() as db:
        tx_count = db.query(Transaction).count()
        wallets = {w.id: w.balance for w in
                   db.query(Wallet).filter(Wallet.id.in_([WALLET_HOME_ID, WALLET_AWAY_ID])).all()}

    _assert(
        "8: zero Transaction rows exist (no payout was written)",
        tx_count == 0,
        detail=f"transaction count={tx_count}",
    )
    _assert(
        "9: both legacy Wallet.balance values unchanged",
        wallets.get(WALLET_HOME_ID) == WALLET_BALANCE_SEED
        and wallets.get(WALLET_AWAY_ID) == WALLET_BALANCE_SEED,
        detail=f"home={wallets.get(WALLET_HOME_ID)} away={wallets.get(WALLET_AWAY_ID)} "
               f"expected={WALLET_BALANCE_SEED}",
    )

    # ── Ledger invariants ─────────────────────────────────────────────────────
    escrow_a_after = balance_of(f"escrow:{BET_A_ID}")
    escrow_b_after = balance_of(f"escrow:{BET_B_ID}")
    wallet_home_ledger_after = balance_of(f"wallet:{HOME_ID}")
    wallet_away_ledger_after = balance_of(f"wallet:{AWAY_ID}")

    _assert(
        "10: escrow for bet A unchanged (no partial drain survives)",
        escrow_a_after == escrow_a_before == STAKE_A_CENTS,
        detail=f"before={escrow_a_before}c after={escrow_a_after}c expected={STAKE_A_CENTS}c",
    )
    _assert(
        "11: escrow for bet B unchanged (unequal stake — no symmetric assumption)",
        escrow_b_after == escrow_b_before == STAKE_B_CENTS,
        detail=f"before={escrow_b_before}c after={escrow_b_after}c expected={STAKE_B_CENTS}c",
    )
    _assert(
        "12: both ledger wallet balances unchanged",
        wallet_home_ledger_after == wallet_home_ledger_before
        and wallet_away_ledger_after == wallet_away_ledger_before,
        detail=f"home {wallet_home_ledger_before}c -> {wallet_home_ledger_after}c, "
               f"away {wallet_away_ledger_before}c -> {wallet_away_ledger_after}c",
    )

    with SessionLocal() as db:
        settled_posting_count = (
            db.query(LedgerEntry).filter(LedgerEntry.door == "wager_settled").count()
        )
    _assert(
        "13: zero wager_settled ledger entries exist",
        settled_posting_count == 0,
        detail=f"wager_settled entry count={settled_posting_count}",
    )

    trial_after = trial_balance()
    _assert(
        "14: trial balance is exactly zero",
        trial_after == 0,
        detail=f"trial_balance={trial_after}c (before={trial_before}c)",
    )

    # ── No recovery was authorized ────────────────────────────────────────────
    with SessionLocal() as db:
        audit_count = db.query(SettlementRecoveryAudit).count()
    _assert(
        "15: zero settlement_recovery_audit rows (no recovery authorized yet)",
        audit_count == 0,
        detail=f"audit row count={audit_count}",
    )

    # ── Retry expectations: an ordinary caller must be refused, fail-closed.
    # This is the guard at settlement_engine.py 396 raising at 397. ────────────
    retry_raised = None
    with SessionLocal() as db:
        try:
            settle_week(_WEEK, db, league_id=LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001 — the raise IS the expected result
            retry_raised = exc

    _assert(
        "16: ordinary retry raises ValueError requiring manual recovery",
        isinstance(retry_raised, ValueError)
        and "recovery" in str(retry_raised).lower(),
        detail=(f"raised {type(retry_raised).__name__}: {retry_raised}"
                if retry_raised is not None else "nothing raised — the week was settleable"),
    )

    # ── The refused retry must not have moved anything either ─────────────────
    with SessionLocal() as db:
        ws2 = (
            db.query(WeekSettlement)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK)
            .first()
        )
    _assert(
        "17: row still CLAIMED after the refused retry",
        ws2 is not None and ws2.status == "CLAIMED" and ws2.settled is False,
        detail=f"status={getattr(ws2, 'status', '<none>')!r} "
               f"settled={getattr(ws2, 'settled', '<none>')}",
    )
    _assert(
        "18: trial balance still zero after the refused retry",
        trial_balance() == 0,
        detail=f"trial_balance={trial_balance()}c",
    )


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
    print("RESULT: all 6d-1 post-claim/pre-lock crash assertions PASSED")
