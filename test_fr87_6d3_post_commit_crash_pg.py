"""
test_fr87_6d3_post_commit_crash_pg.py -- FR-8.7 test 6d-3 (PostgreSQL).

SCENARIO (FR_8_7_TEST_6D_SPEC_FROZEN, 6d-3 -- post-commit / pre-return crash).
THE DURABILITY PROOF, and the mirror image of 6d-2. A settle_week process runs
the entire payout loop, stages the joint beef escrow-close posting, the bet
mutations, the payout Transaction, and the COMPLETED flip -- then successfully
COMMITS all of it, and only then dies.

Every one of those must survive. The crash may cost the return value and the
feed events. It may not cost a cent, a bet outcome, or the completion flag.

WHAT THIS PROVES THAT 6d-2 DOES NOT. 6d-2 proved the transaction is atomic in
the losing direction: staged work dies with the process. That green is
compatible with a settlement that never durably lands anything. 6d-3 closes the
other half. The same fixture, the same payout loop, the same joint escrow close,
one injection point later -- and now everything must be durable, exactly once,
with the winner's credit equal to the SUM of two unequal escrows.

Together the two tests bracket commit #2. Before it, nothing survives. After it,
everything does. Neither test alone establishes that.

LINE ANCHORS. Re-verified at HEAD f230d33 by direct read, not from the frozen
spec, whose anchors were taken at 21ec171 and have drifted:

    Phase-1 claim commit            spec  360  ->  362
    Phase-2 commit (payouts+flip)   spec  781  ->  793
    feed block (own session)        spec  782  ->  799-801
    recovery auth commit            spec 1032  -> 1057

WHY THE FEED NEVER RUNS, AND WHY THAT MATTERS. test_support_crash's
_watched_commit calls the real commit first (285) and only then fires _die() for
POST_PHASE2_COMMIT (286-287). So the child dies in the window between the commit
returning at 793 and the feed block opening its own session at 800. Feed logging
is therefore provably unreached, and "zero feed rows" is a POSITIVE assertion
here rather than a caveat.

That ordering is deliberate scope protection. FR-8.7-LOG-5 is open: league_feed
computes payout as amount * odds while settlement pays actual escrow cents. Had
the injection landed after 801, this test would have inherited that defect's
durable output and its money assertions would have had to be written around a
known-wrong writer. 6d-3 proves economic durability. It is not the test that
inherits LOG-5.

WHY WIN/LOSE AND UNEQUAL STAKES. Same reasoning as 6d-2, load-bearing in the
opposite direction. A push produces two independent postings, each returning its
own escrow to its own wallet. A win/lose produces ONE JOINT posting draining both
escrows into the winner's wallet at combined_credit_cents. Unequal scores force
win/lose; unequal stakes make the winner's credit the SUM of two different
numbers, so a symmetric-stake assumption anywhere in the money path computes
something else and fails assertion 12.

    home_score 120.5 vs away_score 98.0  ->  bet A (picked HOME) wins
    durable posting: (escrow:A, -2500), (escrow:B, -4000), (wallet:HOME, +6500)

In 6d-2 the number 6500 was the credit that must NOT land. Here it is the credit
that MUST land, to the cent.

OBSERVED VERSUS INFERRED. Kept explicit per standing evidence discipline.

  Directly observed by this test:
    - the child's exit code and crash marker
    - every durable row and balance read back on fresh sessions after the child
      is dead: lifecycle fields, bet outcomes, escrow balances, wallet credit,
      wager_settled entry count, Transaction row, trial balance
    - recover_week's refusal of a COMPLETED week, and that it wrote no audit row
    - that a plain retry raises nothing and moves nothing
    - zero rows in every feed table

  Inferred from deterministic control flow, not observed:
    - that commit #2 itself executed. This is inferred from the durable COMPLETED
      row plus the injection's position downstream of it, not from watching the
      commit call.
    - that the SettlementReport return at the end of settle_week never executed.
      This follows from os._exit() skipping the remaining frame, not from a
      captured return value. The child cannot report its own absence.

  Discovered by the first execution of this suite, then locked as regression
  guards (assertions 8 and 9). Neither was read from source, and the design
  draft predicted both wrongly:
    - settlement writes TWO Transaction rows for a joint beef, not one: the
      winner's combined credit (+65.00) and the loser's own stake as a debit
      (-40.00). The draft expected one row, inferred from 6d-2's singular
      "staged payout row" phrasing.
    - settlement does NOT mutate legacy Wallet.balance in either direction. The
      draft expected the winner's float to rise. It does not, and not rising is
      the correct behavior under Governing Invariant 10 -- the ledger is
      authority and the legacy float is never incremented.

  Consequence for 6d-2, recorded not acted on. Its assertion 9 claimed both
  legacy balances unchanged, framed as proof the staged payout rolled back.
  Those floats are unchanged on SUCCESS too, so that assertion cannot fail in
  either direction. It is non-discriminating, and 6d-2's banked 20/20 is really
  19 discriminating assertions plus one tautology. No production defect.

ASSERTIONS (25). Crash landed; lifecycle durable; bet outcomes durable; payout
durable; joint escrow close durable; winner credited the exact combined sum;
trial balance zero; recovery refused FOR THE RIGHT REASON; feed unreached;
retry is a true no-op that does not re-stamp completion.

THE RECOVERY REFUSAL CARRIES A DISCRIMINATING CONTROL. recover_week's
exit_evidence is mandatory and must carry a nonempty "category" and
"detail" (settlement_engine.py 855-859), and that gate sits ahead of the
status check. A bare "did it raise?" assertion would therefore pass on a
malformed evidence dict while proving nothing about COMPLETED refusal. So the
week is offered to recover_week twice -- once with valid evidence, once with
evidence that cannot pass the gate -- and assertion 18 requires the two error
messages to differ. That locates the refusal at the status check without
asserting against a refusal string never read from source.

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST -- setup_postgres_test_db() applies its guards, sets DATABASE_URL
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
    print(f"\n[HARNESS ERROR] FR-8.7 6d-3 suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _feed_tables(db) -> list[str]:
    """Discover feed tables from the live schema rather than guessing a model name.

    The feed writer's table identifier was never read during this test's design,
    so it is resolved from information_schema instead of invented. Returning an
    empty list is treated as a harness error by the caller, not as a pass: if
    there is no feed table at all, the zero-feed-rows assertion would be
    vacuously true and would prove nothing.
    """
    from sqlalchemy import text
    rows = db.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name LIKE '%feed%' "
        "ORDER BY table_name"
    )).fetchall()
    return [r[0] for r in rows]


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection begins
    the instant setup succeeds."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from db.schema import (
        SessionLocal,
        League, Team, Matchup, NflSchedule, Wallet, Bet, Transaction,
        BeefChallenge, WeekSettlement, SettlementRecoveryAudit,
    )
    from ledger.ledger import post as ledger_post, balance_of, trial_balance, LedgerEntry
    from betting.settlement_engine import settle_week, recover_week
    from betting.per_bet_lock import LOCK_SEASON
    from config import CURRENT_SEASON as SEASON

    from test_support_crash import (
        run_settle_week_crashing, assert_crashed, POST_PHASE2_COMMIT,
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
    COMBINED_CENTS = STAKE_A_CENTS + STAKE_B_CENTS   # 6500 -- the credit that MUST land

    FUND_CENTS = 20_000
    WALLET_BALANCE_SEED = 500.00

    # -- League ----------------------------------------------------------------
    with SessionLocal() as _db:
        league = League(season=SEASON, name="FR-8.7 6d-3 Post-Commit Crash League",
                        projection_source="fantasypros")
        _db.add(league)
        _db.commit()
        LEAGUE_ID = league.id

    # -- Two Teams -------------------------------------------------------------
    with SessionLocal() as _db:
        home = Team(league_id=LEAGUE_ID, team_name="6d3 Home", owner="home6d3",
                    email="home@6d3test.com")
        away = Team(league_id=LEAGUE_ID, team_name="6d3 Away", owner="away6d3",
                    email="away@6d3test.com")
        _db.add(home)
        _db.add(away)
        _db.commit()
        HOME_ID = home.id
        AWAY_ID = away.id

    # -- Wallets (legacy Float balances) ---------------------------------------
    with SessionLocal() as _db:
        wh = Wallet(team_id=HOME_ID, balance=WALLET_BALANCE_SEED)
        wa = Wallet(team_id=AWAY_ID, balance=WALLET_BALANCE_SEED)
        _db.add(wh)
        _db.add(wa)
        _db.commit()
        WALLET_HOME_ID = wh.id
        WALLET_AWAY_ID = wa.id

    # -- Matchup with UNEQUAL scores. _team_score_for_week() reads the score off
    # whichever side of this matchup the team sits on, so these two numbers are
    # what _eval_beef compares. -------------------------------------------------
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

    # -- Matched beef pair, both pending. bet A picks HOME (the winner). --------
    with SessionLocal() as _db:
        bet_a = Bet(matchup_id=MATCHUP_ID, wallet_id=WALLET_HOME_ID,
                    picked_team_id=HOME_ID, bet_type="straight",
                    amount=STAKE_A, odds=2.60, status="pending",
                    description="6d-3 beef challenger (HOME, wins)")
        bet_b = Bet(matchup_id=MATCHUP_ID, wallet_id=WALLET_AWAY_ID,
                    picked_team_id=AWAY_ID, bet_type="straight",
                    amount=STAKE_B, odds=1.625, status="pending",
                    description="6d-3 beef challenged (AWAY, loses)")
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

    # -- Resolve the feed table(s) BEFORE the crash. If the schema has none, the
    # zero-feed-rows assertion would be vacuous, so refuse to run rather than
    # bank a meaningless green. -------------------------------------------------
    with SessionLocal() as _db:
        FEED_TABLES = _feed_tables(_db)
    if not FEED_TABLES:
        print("\n[HARNESS ERROR] FR-8.7 6d-3 suite cannot run:\n"
              "  No public-schema table matching '%feed%' exists in the test DB.\n"
              "  'Zero feed rows' would be vacuously true. Resolve the feed\n"
              "  table identifier and re-run.")
        sys.exit(2)
    print(f"  (seed) feed tables under assertion: {FEED_TABLES}")

    # -- Fund the ledger through the real doors, then place both stakes. --------
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
    print(f"  (seed) the credit that MUST land is "
          f"{COMBINED_CENTS}c to wallet:{HOME_ID} "
          f"(= {STAKE_A_CENTS}c + {STAKE_B_CENTS}c, unequal)")

    # -- THE CRASH -- commit #2 at 793 runs to completion, then the child dies
    # before the feed block at 799-801 and before the report return. -----------
    proc = run_settle_week_crashing(_WEEK, LEAGUE_ID, POST_PHASE2_COMMIT)
    crashed, crash_detail = assert_crashed(proc)

    # 0. Fixture proof. The injection fires only after the real commit returns,
    # so a clean crash here means Phase 2 committed and the process then died
    # inside the post-commit window. A traceback exit instead would mean the
    # payout loop failed and there is nothing durable to assert about.
    _assert(
        "0: child committed Phase 2 and crashed immediately after (post-commit window)",
        crashed,
        detail=crash_detail,
    )

    # -- Durable week_settlements state: the COMPLETED flip survived -----------
    with SessionLocal() as db:
        ws_rows = (
            db.query(WeekSettlement)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK)
            .all()
        )
        ws = ws_rows[0] if ws_rows else None
        ws_count = len(ws_rows)
        settled_at_after_crash = getattr(ws, "settled_at", None)

    _assert(
        "1: exactly one week_settlements row exists",
        ws_count == 1,
        detail=f"row count={ws_count}",
    )
    _assert(
        "2: status is COMPLETED (the flip survived the crash)",
        ws is not None and ws.status == "COMPLETED",
        detail=f"status={getattr(ws, 'status', '<none>')!r}",
    )
    _assert(
        "3: settled is True",
        ws is not None and ws.settled is True,
        detail=f"settled={getattr(ws, 'settled', '<none>')}",
    )
    _assert(
        "4: settled_at is durable and non-null",
        settled_at_after_crash is not None,
        detail=f"settled_at={settled_at_after_crash}",
    )
    _assert(
        "5: recovery_token is None (the atomic completion cleared it)",
        ws is not None and ws.recovery_token is None,
        detail=f"recovery_token={getattr(ws, 'recovery_token', '<none>')!r}",
    )

    # -- Durable bet outcomes --------------------------------------------------
    with SessionLocal() as db:
        bet_map = {
            b.id: b for b in
            db.query(Bet).filter(Bet.id.in_([BET_A_ID, BET_B_ID])).all()
        }
        status_a = bet_map[BET_A_ID].status
        status_b = bet_map[BET_B_ID].status
        settled_at_a = bet_map[BET_A_ID].settled_at
        settled_at_b = bet_map[BET_B_ID].settled_at

    _assert(
        "6: winner bet won, loser bet lost (outcomes durable)",
        status_a == "won" and status_b == "lost",
        detail=f"bet A (HOME, 120.5)={status_a!r} bet B (AWAY, 98.0)={status_b!r}",
    )
    _assert(
        "7: both bets carry a durable settled_at",
        settled_at_a is not None and settled_at_b is not None,
        detail=f"A={settled_at_a} B={settled_at_b}",
    )

    # -- Durable payout Transaction journal.
    #
    # DISCOVERED BY THE FIRST 6d-3 RUN, not read from source. Settlement writes
    # TWO Transaction rows for a joint beef, not one:
    #
    #     winner wallet  ->  +65.00  (the combined escrow credit)
    #     loser  wallet  ->  -40.00  (the losing stake)
    #
    # The design draft expected one row, off 6d-2's singular "staged payout row"
    # phrasing. That expectation was wrong and this assertion caught it.
    #
    # Both amounts are asserted against the fixture constants rather than the
    # observed literals, so they stay load-bearing on the unequal stakes: the
    # winner's row must equal the SUM of two different escrows, and the loser's
    # must equal its own stake alone. The winner figure also corroborates
    # assertion 12 through an entirely separate table -- the ledger says 6500c,
    # the Transaction journal says 65.00, and neither derives from the other.
    EXPECTED_WINNER_TX = round(COMBINED_CENTS / 100, 2)     # 65.00
    EXPECTED_LOSER_TX = round(-STAKE_B, 2)                  # -40.00

    with SessionLocal() as db:
        tx_rows = db.query(Transaction).all()
        tx_count = len(tx_rows)
        tx_by_wallet = {t.wallet_id: round(t.amount, 2) for t in tx_rows}
        wallets_legacy = {
            w.id: w.balance for w in
            db.query(Wallet).filter(Wallet.id.in_([WALLET_HOME_ID, WALLET_AWAY_ID])).all()
        }

    _assert(
        "8: two payout Transaction rows -- winner credited the combined sum, "
        "loser debited its own stake",
        tx_count == 2
        and tx_by_wallet.get(WALLET_HOME_ID) == EXPECTED_WINNER_TX
        and tx_by_wallet.get(WALLET_AWAY_ID) == EXPECTED_LOSER_TX,
        detail=f"count={tx_count} by_wallet={tx_by_wallet} "
               f"expected winner(id={WALLET_HOME_ID})={EXPECTED_WINNER_TX} "
               f"loser(id={WALLET_AWAY_ID})={EXPECTED_LOSER_TX}",
    )

    # Legacy Wallet.balance is NOT mutated by settlement, in either direction.
    #
    # ALSO DISCOVERED BY THE FIRST RUN. The draft asserted the winner's float
    # rises; it does not. That is Governing Invariant 10 holding: the ledger is
    # authority and the legacy float is never incremented. This assertion is now
    # a regression guard against something starting to increment it -- which
    # would reintroduce a second, drifting source of truth for balances.
    #
    # NOTE ON 6d-2. Its assertion 9 made the same "unchanged" claim, but framed
    # as proof that the staged payout rolled back. Since these floats are
    # unchanged on SUCCESS too, that assertion cannot fail in either direction.
    # It is non-discriminating. Recorded here because 6d-2's green is banked
    # evidence and its strength is one assertion lower than logged.
    _assert(
        "9: legacy Wallet.balance untouched by settlement (ledger is authority)",
        wallets_legacy.get(WALLET_HOME_ID) == WALLET_BALANCE_SEED
        and wallets_legacy.get(WALLET_AWAY_ID) == WALLET_BALANCE_SEED,
        detail=f"home={wallets_legacy.get(WALLET_HOME_ID)} "
               f"away={wallets_legacy.get(WALLET_AWAY_ID)} seed={WALLET_BALANCE_SEED} "
               f"(a rise here would mean a second source of truth for balances)",
    )

    # -- THE CENTRAL ASSERTIONS -- the joint escrow close is durable, exactly --
    escrow_a_after = balance_of(f"escrow:{BET_A_ID}")
    escrow_b_after = balance_of(f"escrow:{BET_B_ID}")
    wallet_home_ledger_after = balance_of(f"wallet:{HOME_ID}")
    wallet_away_ledger_after = balance_of(f"wallet:{AWAY_ID}")

    _assert(
        "10: winner escrow drained to zero (durable)",
        escrow_a_after == 0,
        detail=f"before={escrow_a_before}c after={escrow_a_after}c",
    )
    _assert(
        "11: loser escrow drained to zero (durable, unequal stake)",
        escrow_b_after == 0,
        detail=f"before={escrow_b_before}c after={escrow_b_after}c",
    )
    _assert(
        "12: winner wallet credited the EXACT combined escrow sum",
        wallet_home_ledger_after == wallet_home_ledger_before + COMBINED_CENTS,
        detail=f"{wallet_home_ledger_before}c -> {wallet_home_ledger_after}c "
               f"(delta={wallet_home_ledger_after - wallet_home_ledger_before}c, "
               f"required={COMBINED_CENTS}c = {STAKE_A_CENTS}c + {STAKE_B_CENTS}c)",
    )
    _assert(
        "13: loser wallet received nothing",
        wallet_away_ledger_after == wallet_away_ledger_before,
        detail=f"{wallet_away_ledger_before}c -> {wallet_away_ledger_after}c",
    )

    with SessionLocal() as db:
        settled_entry_count = (
            db.query(LedgerEntry).filter(LedgerEntry.door == "wager_settled").count()
        )
    _assert(
        "14: exactly three wager_settled ledger entries (one joint 3-leg posting)",
        settled_entry_count == 3,
        detail=f"wager_settled entry count={settled_entry_count} "
               f"(2 escrow debits + 1 wallet credit; more would mean duplicate settlement)",
    )

    trial_after = trial_balance()
    _assert(
        "15: trial balance is exactly zero after durable settlement",
        trial_after == 0,
        detail=f"trial_balance={trial_after}c (before={trial_before}c)",
    )

    # -- The completed week is not recoverable. recover_week's STEP 4 sees
    # non-CLAIMED and aborts. ---------------------------------------------------
    with SessionLocal() as db:
        audit_count_before = db.query(SettlementRecoveryAudit).count()
    _assert(
        "16: zero recovery audit rows exist before the recovery attempt",
        audit_count_before == 0,
        detail=f"audit row count={audit_count_before}",
    )

    # exit_evidence is MANDATORY and MUST carry a nonempty "category" and a
    # nonempty "detail" (settlement_engine.py 855-859). Supplying anything else
    # trips the evidence gate BEFORE the status check, and a bare "did it raise?"
    # assertion would then pass for entirely the wrong reason. Assertion 18
    # exists to prove it did not.
    VALID_EVIDENCE = {
        "category": "process_exit",
        "detail": (f"FR-8.7 6d-3 POST_PHASE2_COMMIT injected crash; "
                   f"child exit code {proc.returncode}, crash marker observed"),
    }
    MALFORMED_EVIDENCE = {"scenario": "6d-3 discriminating control"}

    recover_raised = None
    with SessionLocal() as db:
        try:
            recover_week(
                _WEEK, db,
                league_id=LEAGUE_ID,
                actor="fr87-6d3-test",
                exit_evidence=VALID_EVIDENCE,
            )
        except Exception as exc:  # noqa: BLE001 -- the refusal IS the expected result
            recover_raised = exc

    _assert(
        "17: recover_week refuses the COMPLETED week (valid evidence supplied)",
        recover_raised is not None,
        detail=(f"raised {type(recover_raised).__name__}: {recover_raised}"
                if recover_raised is not None
                else "nothing raised -- a settled week was accepted for recovery"),
    )

    # Discriminating control. Call again with evidence that CANNOT satisfy the
    # gate. If assertion 17's raise came from the evidence gate rather than the
    # status check, these two messages are the same and this fails. Comparing
    # observed messages avoids asserting against a refusal string never read
    # from source.
    control_raised = None
    with SessionLocal() as db:
        try:
            recover_week(
                _WEEK, db,
                league_id=LEAGUE_ID,
                actor="fr87-6d3-test",
                exit_evidence=MALFORMED_EVIDENCE,
            )
        except Exception as exc:  # noqa: BLE001
            control_raised = exc

    _assert(
        "18: the refusal is the status check, NOT the evidence gate "
        "(valid-evidence and malformed-evidence errors differ)",
        recover_raised is not None
        and control_raised is not None
        and str(recover_raised) != str(control_raised),
        detail=(f"valid-evidence raise: {type(recover_raised).__name__}: {recover_raised} | "
                f"malformed-evidence raise: {type(control_raised).__name__}: {control_raised}"),
    )

    with SessionLocal() as db:
        audit_count_after = db.query(SettlementRecoveryAudit).count()
    _assert(
        "19: neither refused recovery wrote an audit row",
        audit_count_after == 0,
        detail=f"audit row count={audit_count_after} (a pre-commit refusal must not audit)",
    )

    # -- The feed was never reached. The child died between the commit at 793
    # and the feed session at 800. --------------------------------------------
    feed_counts = {}
    with SessionLocal() as db:
        for tname in FEED_TABLES:
            # Table names come from information_schema, not user input.
            feed_counts[tname] = db.execute(
                text(f'SELECT count(*) FROM "{tname}"')
            ).scalar()
    _assert(
        "20: zero rows in every feed table (crash landed before the feed block)",
        all(c == 0 for c in feed_counts.values()),
        detail=f"counts={feed_counts}",
    )

    # -- Retry expectations. A plain settle_week on a COMPLETED week takes the
    # idempotent no-op path. It is NOT commit-free: the ON CONFLICT DO NOTHING
    # insert commits at 362 before the conflict status is ever read. So the
    # assertion is zero durable economic and lifecycle change, not zero commits.
    snapshot_before_retry = {
        "escrow_a": balance_of(f"escrow:{BET_A_ID}"),
        "escrow_b": balance_of(f"escrow:{BET_B_ID}"),
        "wallet_home": balance_of(f"wallet:{HOME_ID}"),
        "wallet_away": balance_of(f"wallet:{AWAY_ID}"),
        "trial": trial_balance(),
    }
    with SessionLocal() as db:
        snapshot_before_retry["wager_settled"] = (
            db.query(LedgerEntry).filter(LedgerEntry.door == "wager_settled").count()
        )
        snapshot_before_retry["tx_count"] = db.query(Transaction).count()
        snapshot_before_retry["ledger_total"] = db.query(LedgerEntry).count()

    retry_raised = None
    retry_result = None
    with SessionLocal() as db:
        try:
            retry_result = settle_week(_WEEK, db, league_id=LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001
            retry_raised = exc

    _assert(
        "21: plain retry returns the idempotent no-op and raises nothing",
        retry_raised is None,
        detail=(f"returned {type(retry_result).__name__}"
                if retry_raised is None
                else f"raised {type(retry_raised).__name__}: {retry_raised}"),
    )

    with SessionLocal() as db:
        ws2 = (
            db.query(WeekSettlement)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK)
            .one()
        )
        settled_at_after_retry = ws2.settled_at
        status_after_retry = ws2.status
        settled_after_retry = ws2.settled
        token_after_retry = ws2.recovery_token
        ws_count_after_retry = (
            db.query(WeekSettlement).filter_by(league_id=LEAGUE_ID, week=_WEEK).count()
        )

    # Identity, not merely non-null. A no-op path that quietly re-stamps
    # completion would pass a non-null check and fail this one.
    _assert(
        "22: settled_at is the IDENTICAL timestamp after the retry (no re-stamp)",
        settled_at_after_retry == settled_at_after_crash,
        detail=f"after crash={settled_at_after_crash} after retry={settled_at_after_retry}",
    )
    _assert(
        "23: lifecycle fields unchanged by the retry",
        status_after_retry == "COMPLETED"
        and settled_after_retry is True
        and token_after_retry is None
        and ws_count_after_retry == 1,
        detail=f"status={status_after_retry!r} settled={settled_after_retry} "
               f"token={token_after_retry!r} rows={ws_count_after_retry}",
    )

    snapshot_after_retry = {
        "escrow_a": balance_of(f"escrow:{BET_A_ID}"),
        "escrow_b": balance_of(f"escrow:{BET_B_ID}"),
        "wallet_home": balance_of(f"wallet:{HOME_ID}"),
        "wallet_away": balance_of(f"wallet:{AWAY_ID}"),
        "trial": trial_balance(),
    }
    with SessionLocal() as db:
        snapshot_after_retry["wager_settled"] = (
            db.query(LedgerEntry).filter(LedgerEntry.door == "wager_settled").count()
        )
        snapshot_after_retry["tx_count"] = db.query(Transaction).count()
        snapshot_after_retry["ledger_total"] = db.query(LedgerEntry).count()

    # Full snapshot equality, not just trial balance: a compensating pair of
    # wrong postings would still sum to zero. Entry COUNTS are included so a
    # second settlement that happened to net to the same balances still fails.
    deltas = {
        k: (snapshot_before_retry[k], snapshot_after_retry[k])
        for k in snapshot_before_retry
        if snapshot_before_retry[k] != snapshot_after_retry[k]
    }
    _assert(
        "24: the retry moved no money and wrote no ledger entry (snapshot identical)",
        not deltas,
        detail=("all balances, entry counts and transaction counts identical"
                if not deltas else f"CHANGED={deltas}"),
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
    print("RESULT: all 6d-3 post-commit durability assertions PASSED")
