"""
test_fr87_6d2_mid_payout_pre_commit_crash_pg.py — FR-8.7 test 6d-2 (PostgreSQL).

SCENARIO (FR_8_7_TEST_6D_SPEC_FROZEN, 6d-2 — mid-payout / pre-commit crash).
THE CENTRAL ATOMICITY PROOF. A settle_week process runs the entire payout loop,
stages the joint beef escrow-close posting, the bet status mutations, the payout
Transaction, and the COMPLETED flip — then dies before the single Phase-2 commit.

Every one of those must vanish. No partial escrow drain may survive.

WHAT THIS PROVES THAT 6d-1 DOES NOT. 6d-1 crashed before Phase 2 began, so
nothing had staged; its green was durability of an already-committed claim. Here
real economic work is staged and pending in an open transaction when the process
dies. The assertion is that `session=db` plus one commit at settlement_engine.py
793 makes the whole week's payouts all-or-nothing.

LINE ANCHORS. Re-verified at HEAD f230d33. The frozen spec's anchors were taken
at 21ec171 and have drifted:

    Phase-1 claim commit            spec 360  ->  362
    joint beef escrow-close post    spec  —   ->  607-614
    COMPLETED flip UPDATE           spec  —   ->  751-758 (normal claimant)
    Phase-2 commit (payouts+flip)   spec 781  ->  793

WHY THE INJECTION POINT IS ALSO THE LOOP-LIVENESS PROOF. PRE_PHASE2_COMMIT fires
on the SECOND commit of the settlement session. Commit #2 is at 793, downstream
of the whole payout loop AND the completion UPDATE. So if the injection fires at
all, execution provably reached the end of the loop. Had _eval_beef raised, or
the partner-bet guard tripped, commit #2 would never occur, the child would exit
with a traceback, and assert_crashed() would reject it. Assertion 0 therefore
does double duty: it proves the crash landed where we asked AND that there was
real staged work to lose. Without that, "everything rolled back" could pass
vacuously on a loop that never ran.

WHY WIN/LOSE AND NOT PUSH. The beef branch has two shapes. A push produces two
INDEPENDENT postings, each returning its own escrow to its own wallet (605-570).
A win/lose produces ONE JOINT posting draining both escrows into the winner's
wallet at combined_credit_cents (607-614). The spec asks for the injection to
land after "the joint escrow-close posting is staged", so this suite forces
win/lose by seeding UNEQUAL matchup scores. 6d-1's zero-zero scores would have
evaluated to push.

    home_score 120.5 vs away_score 98.0  ->  bet A (picked HOME) wins
    staged posting: (escrow:A, -2500), (escrow:B, -4000), (wallet:HOME, +6500)

Stakes are deliberately UNEQUAL ($25 / $40). The winner's credit is the SUM of
two different escrow balances, so a symmetric-stake assumption anywhere in the
money path would produce a different number and fail assertion 12.

SCOPE. This is the rollback half of 6d-2. The frozen spec also expects an
authorized recovery to then settle the week cleanly, exercising recover_week's
STEP 5 gate (re-checking that all bets are still pending — which they are,
precisely because this rollback worked). That leg needs recover_week's
actor/exit_evidence surface and shares all its machinery with 6d-5, so it is
built there rather than duplicated here. OUTSTANDING, not dropped.

ASSERTIONS (20). Durable state, zero bets touched, zero payouts, ledger
invariants, no recovery authorized, retry expectations — and, first, the fixture
and loop-liveness proof.

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — setup_postgres_test_db() applies its guards, sets DATABASE_URL
# to the disposable test DB, and imports+binds db.schema INTERNALLY. No project
# module may be imported before this call.
from test_support_postgres import setup_postgres_test_db

import datetime as _dt
#: S6 §8 — the instant this suite's fixture weeks are declared economically
#: final at. Fixed rather than now(): a fixture's finality must not drift with
#: the wall clock, and Matchup.finalized_at is the ONLY signal the shared
#: settlement gate reads. Stating it makes the completed-week premise these
#: scenarios always relied on explicit instead of implicit.
_FIXTURE_FINAL_AT = _dt.datetime(2025, 12, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)


try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] FR-8.7 6d-2 suite cannot run:\n  {e}")
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

    from test_support_crash import (
        run_settle_week_crashing, assert_crashed, PRE_PHASE2_COMMIT,
    )

    FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)
    _WEEK = 1

    # UNEQUAL scores force the win/lose branch (the joint escrow close), not the
    # push branch. HOME wins, and bet A picked HOME.
    HOME_SCORE = 120.5
    AWAY_SCORE = 98.0

    # UNEQUAL stakes. The winner's credit is the SUM of two different escrow
    # balances; a symmetric-stake assumption would compute something else.
    STAKE_A = 25.00
    STAKE_B = 40.00
    STAKE_A_CENTS = int(round(STAKE_A * 100))
    STAKE_B_CENTS = int(round(STAKE_B * 100))
    COMBINED_CENTS = STAKE_A_CENTS + STAKE_B_CENTS   # 6500 — the credit that must NOT land

    FUND_CENTS = 20_000
    WALLET_BALANCE_SEED = 500.00

    # ── League ────────────────────────────────────────────────────────────────
    with SessionLocal() as _db:
        league = League(season=SEASON, name="FR-8.7 6d-2 Mid-Payout Crash League",
                        projection_source="fantasypros")
        _db.add(league)
        _db.commit()
        LEAGUE_ID = league.id

    # ── Two Teams ─────────────────────────────────────────────────────────────
    with SessionLocal() as _db:
        home = Team(league_id=LEAGUE_ID, team_name="6d2 Home", owner="home6d2",
                    email="home@6d2test.com")
        away = Team(league_id=LEAGUE_ID, team_name="6d2 Away", owner="away6d2",
                    email="away@6d2test.com")
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

    # ── Matchup with UNEQUAL scores. _team_score_for_week() reads the score off
    # whichever side of this matchup the team sits on, so these two numbers are
    # what _eval_beef compares. ───────────────────────────────────────────────
    with SessionLocal() as _db:
        m = Matchup(league_id=LEAGUE_ID, week=_WEEK,
                    home_team_id=HOME_ID, away_team_id=AWAY_ID,
                    home_score=HOME_SCORE, away_score=AWAY_SCORE,
                    # S6 §8 — a COMPLETED week, stated explicitly.
                    finalized_at=_FIXTURE_FINAL_AT)
        _db.add(m)
        _db.add(NflSchedule(season=LOCK_SEASON, week=_WEEK,
                            home_team="KC", away_team="PHI",
                            kickoff_utc=FUTURE_KO))
        _db.commit()
        MATCHUP_ID = m.id

    # ── Matched beef pair, both pending. bet A picks HOME (the winner). ───────
    with SessionLocal() as _db:
        bet_a = Bet(matchup_id=MATCHUP_ID, wallet_id=WALLET_HOME_ID,
                    picked_team_id=HOME_ID, bet_type="straight",
                    amount=STAKE_A, odds=2.60, status="pending",
                    description="6d-2 beef challenger (HOME, wins)")
        bet_b = Bet(matchup_id=MATCHUP_ID, wallet_id=WALLET_AWAY_ID,
                    picked_team_id=AWAY_ID, bet_type="straight",
                    amount=STAKE_B, odds=1.625, status="pending",
                    description="6d-2 beef challenged (AWAY, loses)")
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

    # ── Fund the ledger through the real doors, then place both stakes. ───────
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

    escrow_a_before = balance_of(f"escrow:{BET_A_ID}")
    escrow_b_before = balance_of(f"escrow:{BET_B_ID}")
    wallet_home_ledger_before = balance_of(f"wallet:{HOME_ID}")
    wallet_away_ledger_before = balance_of(f"wallet:{AWAY_ID}")
    trial_before = trial_balance()

    print(f"  (seed) escrow:{BET_A_ID}={escrow_a_before}c  "
          f"escrow:{BET_B_ID}={escrow_b_before}c  "
          f"wallet:{HOME_ID}={wallet_home_ledger_before}c  trial={trial_before}c")
    print(f"  (seed) the staged-then-rolled-back credit would be "
          f"{COMBINED_CENTS}c to wallet:{HOME_ID}")

    # ── THE CRASH — after the payout loop and the COMPLETED flip are staged,
    # immediately before the single Phase-2 commit at 793. ────────────────────
    proc = run_settle_week_crashing(_WEEK, LEAGUE_ID, PRE_PHASE2_COMMIT)
    crashed, crash_detail = assert_crashed(proc)

    # 0. Fixture AND loop-liveness proof. Commit #2 sits downstream of the whole
    # payout loop, so the injection firing means the loop ran to completion with
    # real work staged. Without this, every assertion below could pass vacuously
    # on a loop that never executed.
    _assert(
        "0: child reached commit #2 and crashed there (loop ran, work was staged)",
        crashed,
        detail=crash_detail,
    )

    # ── Durable week_settlements state: the COMPLETED flip rolled back ────────
    with SessionLocal() as db:
        ws_rows = (
            db.query(WeekSettlement)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK)
            .all()
        )
        ws = ws_rows[0] if ws_rows else None
        ws_count = len(ws_rows)

    _assert(
        "1: exactly one week_settlements row exists",
        ws_count == 1,
        detail=f"row count={ws_count}",
    )
    _assert(
        "2: status is still CLAIMED (the staged COMPLETED flip rolled back)",
        ws is not None and ws.status == "CLAIMED",
        detail=f"status={getattr(ws, 'status', '<none>')!r}",
    )
    _assert(
        "3: settled is False (the staged settled=TRUE rolled back)",
        ws is not None and ws.settled is False,
        detail=f"settled={getattr(ws, 'settled', '<none>')}",
    )
    _assert(
        "4: settled_at is None (the staged completion timestamp rolled back)",
        ws is not None and ws.settled_at is None,
        detail=f"settled_at={getattr(ws, 'settled_at', '<none>')}",
    )
    _assert(
        "5: recovery_token is None (a failed normal run mints no token)",
        ws is not None and ws.recovery_token is None,
        detail=f"recovery_token={getattr(ws, 'recovery_token', '<none>')!r}",
    )

    # ── Zero bets touched: the staged won/lost mutations rolled back ──────────
    with SessionLocal() as db:
        bets = db.query(Bet).filter(Bet.id.in_([BET_A_ID, BET_B_ID])).order_by(Bet.id).all()
        statuses = [b.status for b in bets]
        settled_ats = [b.settled_at for b in bets]

    _assert(
        "6: both bets still pending (staged won/lost mutations rolled back)",
        statuses == ["pending", "pending"],
        detail=f"statuses={statuses} (staged were ['won','lost'])",
    )
    _assert(
        "7: neither bet has settled_at set",
        all(s is None for s in settled_ats),
        detail=f"settled_at={settled_ats}",
    )

    # ── Zero payouts: the staged payout Transaction rolled back ──────────────
    with SessionLocal() as db:
        tx_count = db.query(Transaction).count()
        wallets = {w.id: w.balance for w in
                   db.query(Wallet).filter(Wallet.id.in_([WALLET_HOME_ID, WALLET_AWAY_ID])).all()}

    _assert(
        "8: zero Transaction rows exist (staged payout row rolled back)",
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

    # ── THE CENTRAL ASSERTIONS — no partial escrow drain survives ────────────
    escrow_a_after = balance_of(f"escrow:{BET_A_ID}")
    escrow_b_after = balance_of(f"escrow:{BET_B_ID}")
    wallet_home_ledger_after = balance_of(f"wallet:{HOME_ID}")
    wallet_away_ledger_after = balance_of(f"wallet:{AWAY_ID}")

    _assert(
        "10: winner escrow NOT drained (staged -2500 rolled back)",
        escrow_a_after == escrow_a_before == STAKE_A_CENTS,
        detail=f"before={escrow_a_before}c after={escrow_a_after}c expected={STAKE_A_CENTS}c",
    )
    _assert(
        "11: loser escrow NOT drained (staged -4000 rolled back, unequal stake)",
        escrow_b_after == escrow_b_before == STAKE_B_CENTS,
        detail=f"before={escrow_b_before}c after={escrow_b_after}c expected={STAKE_B_CENTS}c",
    )
    _assert(
        "12: winner wallet did NOT receive the combined credit",
        wallet_home_ledger_after == wallet_home_ledger_before,
        detail=f"{wallet_home_ledger_before}c -> {wallet_home_ledger_after}c; "
               f"a surviving credit would show +{COMBINED_CENTS}c "
               f"(= {STAKE_A_CENTS}c + {STAKE_B_CENTS}c)",
    )
    _assert(
        "13: loser wallet unchanged",
        wallet_away_ledger_after == wallet_away_ledger_before,
        detail=f"{wallet_away_ledger_before}c -> {wallet_away_ledger_after}c",
    )

    with SessionLocal() as db:
        settled_entry_count = (
            db.query(LedgerEntry).filter(LedgerEntry.door == "wager_settled").count()
        )
    _assert(
        "14: zero wager_settled ledger entries (the staged 3-leg posting rolled back)",
        settled_entry_count == 0,
        detail=f"wager_settled entry count={settled_entry_count} (staged were 3)",
    )

    trial_after = trial_balance()
    _assert(
        "15: trial balance is exactly zero",
        trial_after == 0,
        detail=f"trial_balance={trial_after}c (before={trial_before}c)",
    )

    # ── No recovery was authorized by the crashed run ─────────────────────────
    with SessionLocal() as db:
        audit_count = db.query(SettlementRecoveryAudit).count()
    _assert(
        "16: zero settlement_recovery_audit rows",
        audit_count == 0,
        detail=f"audit row count={audit_count}",
    )

    # ── Retry expectations: an ordinary caller is refused, fail-closed.
    # Guard at settlement_engine.py 396 raising at 397. ───────────────────────
    retry_raised = None
    with SessionLocal() as db:
        try:
            settle_week(_WEEK, db, league_id=LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001 — the raise IS the expected result
            retry_raised = exc

    _assert(
        "17: ordinary retry raises ValueError requiring manual recovery",
        isinstance(retry_raised, ValueError)
        and "recovery" in str(retry_raised).lower(),
        detail=(f"raised {type(retry_raised).__name__}: {retry_raised}"
                if retry_raised is not None else "nothing raised — the week was settleable"),
    )

    # ── The refused retry moved nothing either. Escrow is re-read rather than
    # only re-checking trial balance: a compensating pair of wrong postings
    # would still sum to zero. ───────────────────────────────────────────────
    _assert(
        "18: both escrows still intact after the refused retry",
        balance_of(f"escrow:{BET_A_ID}") == STAKE_A_CENTS
        and balance_of(f"escrow:{BET_B_ID}") == STAKE_B_CENTS,
        detail=f"A={balance_of(f'escrow:{BET_A_ID}')}c B={balance_of(f'escrow:{BET_B_ID}')}c",
    )
    _assert(
        "19: trial balance still zero after the refused retry",
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
    print("RESULT: all 6d-2 mid-payout/pre-commit atomicity assertions PASSED")
