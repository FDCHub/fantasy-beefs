"""
test_fr87_6d5a_recovery_authority_pg.py -- FR-8.7 test 6d-5a (PostgreSQL).

SCENARIO. The sequential half of frozen 6d-5, plus the authorized-recovery leg
that 6d-2 deliberately deferred rather than dropped.

6d-5 as frozen is a race: a recovery settle_week(recovery_token=current) against
a normal settle_week(recovery_token=None), coordinated around the Phase-2
FOR UPDATE. That proof needs genuine overlapping transactions and lock ordering,
so it is isolation-gated alongside 6d-4 and 6d-7. This suite takes the half that
needs no concurrency at all, and it is the larger half: everything about how a
recovery is AUTHORIZED, AUDITED, GATED, and settled exactly once.

Ruled 2026-07-30: eight execution units, frozen seven-scenario taxonomy
unchanged. 6d-5a is the correct and only home for 6d-2's deferred recovery leg;
no separate 6d-2 recovery suite is to be created.

WHAT THIS PROVES THAT 6d-1, 6d-2 AND 6d-3 DO NOT. All three ended at a refusal
or a completion reached by the ORDINARY caller. None of them ever exercised
recover_week's authorization path. 6d-3 touched it only to be turned away by a
COMPLETED week. Here a real crashed week is recovered end to end: token minted,
audit written under the lock, safety gate evaluated, settle_week re-entered as
the authorized claimant, and the week settled once and only once.

THE INTERLOCK WITH 6d-2. 6d-2 crashed a settle_week at PRE_PHASE2_COMMIT and
proved every staged effect vanished. That rollback is exactly what makes this
recovery legal: STEP 5's gate re-checks that EVERY league/week bet is still
pending, and they are, precisely because 6d-2's rollback worked. This suite
reproduces that crash as its own precondition and then completes the story. The
two tests are two halves of one proof.

LINE ANCHORS. Read from source at HEAD 49ce24e. recover_week spans 844-1062.

    STEP 1  exit_evidence validation      868
    STEP 3  SELECT ... FOR UPDATE         925
    STEP 4  status recoverability check   940
    STEP 5  pending-bet safety gate       955
    STEP 6  observed_pre_state assembly  1002
    STEP 7  token mint + fingerprint     1019
    STEP 7  token overwrite UNDER LOCK   1038
    STEP 8  audit + token commit         1056
    STEP 9  settle_week re-entry         1059

GATE ORDERING IS NOW VERIFIED, NOT INFERRED. STEP 1 validates exit_evidence at
868 -- before the lock at 925 and well before the COMPLETED refusal at 940. 6d-3
inferred this ordering from two differing error messages, which was adequate for
its purpose but was an inference. It is now read from source.

WHY recover_week CANNOT HAND US A LIVE TOKEN. STEP 7 mints the raw token, STEP 7's
UPDATE writes it to week_settlements.recovery_token, STEP 9 passes it to
settle_week, and the successful COMPLETED flip clears it. The function returns a
SettlementReport, never the token. So a committed-token-on-a-still-CLAIMED-row
state cannot exist after a SUCCESSFUL recovery -- it arises only when a recovery
dies between STEP 8's commit and STEP 9's completion, which is 6d-6's exact
injection point.

Consequence for scope: frozen 6d-5's "normal caller with a live token present is
rejected" leg is NOT tested here. It belongs to 6d-6, where that state is the
natural durable outcome rather than something this suite would have to
manufacture with hand-written SQL. Deferred deliberately, recorded here, not
dropped.

THE ONE SYNTHESIZED PRECONDITION, AND EXACTLY WHAT IT ESTABLISHES. STEP 5 uses
non-pending bet status as its PROXY for committed Phase-2 effects: any bet not
'pending' is taken as evidence that payouts already landed, so the week is not
cleanly recoverable. That state cannot occur naturally -- Phase 2 is a single
transaction, which is the property 6d-2 proved. The gate exists to guard a state
that SHOULD be impossible.

A test of that gate therefore has to manufacture the state. PART 7 does, on a
second league: crash at PRE_LOCK, then set one bet's status to 'won' by direct
UPDATE, so that one bet carries a non-pending status -- the inconsistent state
STEP 5 is designed to reject.

Scope of the claim, stated precisely. The fixture manufactures the STATUS, not
actual committed payout effects: no escrow was drained and no wallet was credited
by the synthesis. So PART 7 proves the GATE works on its own proxy condition. It
does not, and does not claim to, reproduce a real half-settled week. The
mechanism under test -- the gate's evaluation, its refusal, and its rollback of
the audit and token -- is entirely real. Asserting a gate only against states the
system can currently reach would leave it unproven for the one case it was
written for.

THE AUDIT'S ESCROW EVIDENCE IS A TRANSACTION-LOCAL READ PROOF. STEP 5 records
each escrow-backed bet's balance via _balance_of_in_session(db, account) under the
lock, deliberately NOT balance_of(), which opens its own session. Assertion 15
reads those recorded values back out of the durable audit row and requires them to
equal the real, unequal escrow balances.

What that directly establishes: the recovery transaction's session-scoped ledger
read correctly sees the previously committed escrow balances, and durably persists
the two unequal values. A wrong transaction-local read would write wrong numbers
into a column we can inspect after the fact.

What it does NOT establish on its own: the full cross-session visibility boundary
that frozen spec PART C describes. Two simultaneously active sessions are never
exercised here -- the crashed child is dead before recovery begins. This is strong
evidence for the read path, not a concurrency proof. The overlapping-session case
belongs to the isolation-gated units.

WHY UNEQUAL SCORES AND UNEQUAL STAKES, AGAIN. Same construction as 6d-2 and 6d-3,
for the same reason and now load-bearing in a third direction: the recovered
settlement's winner credit must equal the SUM of two DIFFERENT escrow balances,
and the audit's escrow evidence must record those two different numbers
separately. A symmetric-stake assumption anywhere in authorization or payout
produces different values and fails.

    home_score 120.5 vs away_score 98.0  ->  bet A (picked HOME) wins
    recovered posting: (escrow:A, -2500), (escrow:B, -4000), (wallet:HOME, +6500)

OBSERVED VERSUS INFERRED.

  Directly observed:
    - the crashed child's exit code and marker
    - every durable row and balance read back on fresh sessions
    - the audit row's every column, including the recorded escrow evidence
    - recover_week's return value on success, and its refusals with their messages
    - that a completed week refuses a second recovery and no-ops a plain retry
    - that the refused STEP 5 gate wrote no audit row and moved no money

  Inferred, not observed:
    - that STEP 9's settle_week ran as the token-matched claimant rather than by
      some other route. Inferred from the token being cleared by the completion
      flip plus the week reaching COMPLETED, not from watching the guard evaluate.
    - the exact normalization STEP 1 applies to exit_evidence. STEP 1 was outside
      the authorized recon scope, so assertion 11 asserts only that category and
      detail are present and stripped, and REPORTS the full key set rather than
      asserting it.

STATED LIMITATION -- FINGERPRINT CORRESPONDENCE IS NOT PROVEN HERE. Assertion 9
verifies a SHA-256-shaped digest was stored. Assertion 17 verifies no uuid-shaped
raw credential leaked into any audit column. Neither proves the stored digest is
the sha256 OF THAT PARTICULAR live token, because a successful recover_week never
exposes the raw token: STEP 7 mints it, writes it under the lock, hands it to
STEP 9, and the COMPLETED flip clears it.

Proving correspondence requires a run where the token SURVIVES -- which is
precisely 6d-6, whose durable outcome is a committed token on a still-CLAIMED row.
Recorded as a 6d-6 obligation, not an omission here.

ASSERTIONS (37, labelled 0-36) across seven parts:

    PART 1  0-4    crashed precondition -- a cleanly recoverable week
    PART 2  5-6    authorized recovery executes, one audit row
    PART 3  7-17   audit integrity, incl. the cross-session escrow proof (15)
                   and the raw-token-absent scan (17)
    PART 4  18-20  post-recovery lifecycle, token retired
    PART 5  21-28  exactly-once economics, ledger and report corroborating
    PART 6  29-32  post-completion refusals, retry is a true no-op
    PART 7  33-36  STEP 5 safety gate on a synthesized precondition

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST -- setup_postgres_test_db() applies its guards, sets DATABASE_URL
# to the disposable test DB, and imports+binds db.schema INTERNALLY. No project
# module may be imported before this call.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] FR-8.7 6d-5a suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []

# uuid4 string form: 8-4-4-4-12 hex, dash separated. Used to prove the raw
# recovery credential appears in NO audit column.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection begins
    the instant setup succeeds."""
    import json
    from datetime import datetime, timedelta, timezone

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
        run_settle_week_crashing, assert_crashed,
        PRE_LOCK, PRE_PHASE2_COMMIT,
    )

    FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)
    _WEEK = 1

    # Identical construction to 6d-2 and 6d-3. Unequal on both axes.
    HOME_SCORE = 120.5
    AWAY_SCORE = 98.0
    STAKE_A = 25.00
    STAKE_B = 40.00
    STAKE_A_CENTS = int(round(STAKE_A * 100))
    STAKE_B_CENTS = int(round(STAKE_B * 100))
    COMBINED_CENTS = STAKE_A_CENTS + STAKE_B_CENTS   # 6500

    FUND_CENTS = 20_000
    WALLET_BALANCE_SEED = 500.00

    # ----------------------------------------------------------------------
    # Fixture builder. Shared by PART 1's league and PART 7's second league so
    # the two cannot drift apart. Returns every id the assertions need.
    # ----------------------------------------------------------------------
    def _build_beef_week(label: str, add_schedule: bool) -> dict:
        with SessionLocal() as _db:
            league = League(season=SEASON, name=f"FR-8.7 6d-5a {label}",
                            projection_source="fantasypros")
            _db.add(league)
            _db.commit()
            league_id = league.id

        with SessionLocal() as _db:
            home = Team(league_id=league_id, team_name=f"{label} Home",
                        owner=f"home-{label}", email=f"home@{label}.6d5a.test")
            away = Team(league_id=league_id, team_name=f"{label} Away",
                        owner=f"away-{label}", email=f"away@{label}.6d5a.test")
            _db.add(home)
            _db.add(away)
            _db.commit()
            home_id, away_id = home.id, away.id

        with SessionLocal() as _db:
            wh = Wallet(team_id=home_id, balance=WALLET_BALANCE_SEED)
            wa = Wallet(team_id=away_id, balance=WALLET_BALANCE_SEED)
            _db.add(wh)
            _db.add(wa)
            _db.commit()
            wallet_home_id, wallet_away_id = wh.id, wa.id

        with SessionLocal() as _db:
            m = Matchup(league_id=league_id, week=_WEEK,
                        home_team_id=home_id, away_team_id=away_id,
                        home_score=HOME_SCORE, away_score=AWAY_SCORE)
            _db.add(m)
            # NflSchedule is keyed on (season, week), not league. One row only.
            if add_schedule:
                _db.add(NflSchedule(season=LOCK_SEASON, week=_WEEK,
                                    home_team="KC", away_team="PHI",
                                    kickoff_utc=FUTURE_KO))
            _db.commit()
            matchup_id = m.id

        with SessionLocal() as _db:
            bet_a = Bet(matchup_id=matchup_id, wallet_id=wallet_home_id,
                        picked_team_id=home_id, bet_type="straight",
                        amount=STAKE_A, odds=2.60, status="pending",
                        description=f"6d-5a {label} challenger (HOME, wins)")
            bet_b = Bet(matchup_id=matchup_id, wallet_id=wallet_away_id,
                        picked_team_id=away_id, bet_type="straight",
                        amount=STAKE_B, odds=1.625, status="pending",
                        description=f"6d-5a {label} challenged (AWAY, loses)")
            _db.add(bet_a)
            _db.add(bet_b)
            _db.commit()
            bet_a_id, bet_b_id = bet_a.id, bet_b.id

        with SessionLocal() as _db:
            ch = BeefChallenge(
                challenger_team_id   = home_id,
                challenged_team_id   = away_id,
                league_id            = league_id,
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
                challenger_bet_id    = bet_a_id,
                challenged_bet_id    = bet_b_id,
            )
            _db.add(ch)
            _db.commit()
            challenge_id = ch.id

        with SessionLocal() as _db:
            _db.query(Bet).filter(Bet.id.in_([bet_a_id, bet_b_id])).update(
                {"beef_challenge_id": challenge_id}, synchronize_session=False
            )
            _db.commit()

        # Fund through the real doors, then place both stakes.
        ledger_post([("world", -FUND_CENTS), (f"wallet:{home_id}", FUND_CENTS)],
                    door="buy_in_paid")
        ledger_post([("world", -FUND_CENTS), (f"wallet:{away_id}", FUND_CENTS)],
                    door="buy_in_paid")
        ledger_post([(f"wallet:{home_id}", -STAKE_A_CENTS),
                     (f"escrow:{bet_a_id}",  STAKE_A_CENTS)],
                    door="wager_placed")
        ledger_post([(f"wallet:{away_id}", -STAKE_B_CENTS),
                     (f"escrow:{bet_b_id}",  STAKE_B_CENTS)],
                    door="wager_placed")

        return {
            "league_id": league_id,
            "home_id": home_id, "away_id": away_id,
            "wallet_home_id": wallet_home_id, "wallet_away_id": wallet_away_id,
            "bet_a_id": bet_a_id, "bet_b_id": bet_b_id,
            "challenge_id": challenge_id,
        }

    # ======================================================================
    # PART 1 -- the crashed precondition. This IS 6d-2's scenario, reproduced
    # as the starting state rather than as the thing under test.
    # ======================================================================
    print("\n-- PART 1: crashed Phase 2 leaves a cleanly recoverable week --")

    f = _build_beef_week("primary", add_schedule=True)
    LEAGUE_ID = f["league_id"]
    BET_A_ID, BET_B_ID = f["bet_a_id"], f["bet_b_id"]
    HOME_ID, AWAY_ID = f["home_id"], f["away_id"]
    WALLET_HOME_ID, WALLET_AWAY_ID = f["wallet_home_id"], f["wallet_away_id"]

    wallet_home_before = balance_of(f"wallet:{HOME_ID}")
    wallet_away_before = balance_of(f"wallet:{AWAY_ID}")

    proc = run_settle_week_crashing(_WEEK, LEAGUE_ID, PRE_PHASE2_COMMIT)
    crashed, crash_detail = assert_crashed(proc)

    _assert(
        "0: child staged the whole payout loop and died before commit #2",
        crashed,
        detail=crash_detail,
    )

    with SessionLocal() as db:
        ws = db.query(WeekSettlement).filter_by(league_id=LEAGUE_ID, week=_WEEK).one_or_none()
        pre_status = getattr(ws, "status", None)
        pre_settled = getattr(ws, "settled", None)
        pre_settled_at = getattr(ws, "settled_at", None)
        pre_token = getattr(ws, "recovery_token", None)
        pre_bet_statuses = [
            b.status for b in
            db.query(Bet).filter(Bet.id.in_([BET_A_ID, BET_B_ID])).order_by(Bet.id).all()
        ]
        pre_audit_count = db.query(SettlementRecoveryAudit).count()

    _assert(
        "1: week is CLAIMED, unsettled, with no token (recoverable state)",
        pre_status == "CLAIMED" and pre_settled is False
        and pre_settled_at is None and pre_token is None,
        detail=f"status={pre_status!r} settled={pre_settled} "
               f"settled_at={pre_settled_at} token={pre_token!r}",
    )
    _assert(
        "2: every bet still pending (STEP 5's gate will find a clean week)",
        pre_bet_statuses == ["pending", "pending"],
        detail=f"statuses={pre_bet_statuses}",
    )
    escrow_a_pre = balance_of(f"escrow:{BET_A_ID}")
    escrow_b_pre = balance_of(f"escrow:{BET_B_ID}")
    _assert(
        "3: both escrows intact at their unequal amounts, trial balance zero",
        escrow_a_pre == STAKE_A_CENTS and escrow_b_pre == STAKE_B_CENTS
        and trial_balance() == 0,
        detail=f"escrow:{BET_A_ID}={escrow_a_pre}c escrow:{BET_B_ID}={escrow_b_pre}c "
               f"trial={trial_balance()}c",
    )
    _assert(
        "4: the crashed normal run authorized no recovery",
        pre_audit_count == 0,
        detail=f"audit row count={pre_audit_count}",
    )

    # ======================================================================
    # PART 2 -- authorized recovery executes end to end.
    # ======================================================================
    print("\n-- PART 2: authorized recovery executes --")

    VALID_EVIDENCE = {
        "category": "process_exit",
        "detail": (f"  FR-8.7 6d-5a PRE_PHASE2_COMMIT injected crash; "
                   f"child exit code {proc.returncode}, crash marker observed  "),
    }
    ACTOR = "fr87-6d5a-operator"

    recover_error = None
    report = None
    with SessionLocal() as db:
        try:
            report = recover_week(
                _WEEK, db,
                league_id=LEAGUE_ID,
                actor=ACTOR,
                exit_evidence=VALID_EVIDENCE,
            )
        except Exception as exc:  # noqa: BLE001
            recover_error = exc

    _assert(
        "5: recover_week completes and returns a SettlementReport",
        recover_error is None and report is not None,
        detail=(f"returned {type(report).__name__}"
                if recover_error is None
                else f"raised {type(recover_error).__name__}: {recover_error}"),
    )

    with SessionLocal() as db:
        audit_rows = (
            db.query(SettlementRecoveryAudit)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK)
            .order_by(SettlementRecoveryAudit.id)
            .all()
        )
        audit = audit_rows[0] if audit_rows else None
        audit_count = len(audit_rows)
        # Detach the values we need before the session closes.
        a_actor = getattr(audit, "actor", None)
        a_recovered_at = getattr(audit, "recovered_at", None)
        a_fingerprint = getattr(audit, "recovery_token_fingerprint", None)
        a_prior_present = getattr(audit, "prior_recovery_token_present", None)
        a_exit_evidence = dict(getattr(audit, "exit_evidence", {}) or {})
        a_pre_state = dict(getattr(audit, "observed_pre_state", {}) or {})

    _assert(
        "6: exactly one append-only audit row for this authorization",
        audit_count == 1,
        detail=f"audit rows for league={LEAGUE_ID} week={_WEEK}: {audit_count}",
    )

    # ======================================================================
    # PART 3 -- audit integrity.
    # ======================================================================
    print("\n-- PART 3: audit integrity --")

    _assert(
        "7: actor recorded verbatim",
        a_actor == ACTOR,
        detail=f"actor={a_actor!r} expected={ACTOR!r}",
    )
    _assert(
        "8: recovered_at is populated",
        a_recovered_at is not None,
        detail=f"recovered_at={a_recovered_at}",
    )
    _assert(
        "9: token fingerprint is a 64-char lowercase SHA-256 hex digest",
        isinstance(a_fingerprint, str) and bool(_SHA256_RE.match(a_fingerprint)),
        detail=f"fingerprint={a_fingerprint!r} len={len(a_fingerprint or '')}",
    )
    _assert(
        "10: prior_recovery_token_present is False (no stale token on the row)",
        a_prior_present is False,
        detail=f"prior_recovery_token_present={a_prior_present} "
               f"(row token before recovery was {pre_token!r})",
    )
    # STEP 1's normalization was outside authorized recon scope, so assert only
    # what is supportable: category and detail present and stripped. The full key
    # set is REPORTED, not asserted.
    _assert(
        "11: exit_evidence stores category and detail, whitespace stripped",
        a_exit_evidence.get("category") == VALID_EVIDENCE["category"].strip()
        and a_exit_evidence.get("detail") == VALID_EVIDENCE["detail"].strip(),
        detail=f"keys={sorted(a_exit_evidence)} "
               f"category={a_exit_evidence.get('category')!r} "
               f"detail_len={len(str(a_exit_evidence.get('detail', '')))} "
               f"(supplied detail was padded with leading/trailing spaces)",
    )
    _assert(
        "12: observed_pre_state recorded the locked claim status",
        a_pre_state.get("claim_status") == "CLAIMED",
        detail=f"claim_status={a_pre_state.get('claim_status')!r}",
    )
    _assert(
        "13: observed_pre_state recorded both pending bets, by id",
        a_pre_state.get("pending_bet_count") == 2
        and sorted(a_pre_state.get("pending_bet_ids") or []) == sorted([BET_A_ID, BET_B_ID]),
        detail=f"count={a_pre_state.get('pending_bet_count')} "
               f"ids={a_pre_state.get('pending_bet_ids')} "
               f"expected ids={sorted([BET_A_ID, BET_B_ID])}",
    )
    _assert(
        "14: observed_pre_state recorded non_pending_bet_count of 0 (gate held)",
        a_pre_state.get("non_pending_bet_count") == 0,
        detail=f"non_pending_bet_count={a_pre_state.get('non_pending_bet_count')}",
    )

    # THE CROSS-SESSION VISIBILITY PROOF. STEP 5 read these under the lock via
    # _balance_of_in_session, not balance_of. The two values are DIFFERENT, so a
    # symmetric assumption or a wrong session read writes wrong numbers here.
    expected_escrow_evidence = {
        f"escrow:{BET_A_ID}": STAKE_A_CENTS,
        f"escrow:{BET_B_ID}": STAKE_B_CENTS,
    }
    _assert(
        "15: audit durably recorded the real unequal escrow balances "
        "(transaction-local ledger read correct)",
        (a_pre_state.get("escrow_accounts_verified") or {}) == expected_escrow_evidence,
        detail=f"recorded={a_pre_state.get('escrow_accounts_verified')} "
               f"expected={expected_escrow_evidence}",
    )
    _assert(
        "16: observed_pre_state.prior_token_present is False",
        a_pre_state.get("prior_token_present") is False,
        detail=f"prior_token_present={a_pre_state.get('prior_token_present')}",
    )

    # The raw recovery credential must appear in NO audit column. Scan every
    # stored value, including both JSON blobs, for a uuid4-shaped string.
    audit_blob = " | ".join([
        str(a_actor), str(a_fingerprint),
        json.dumps(a_exit_evidence, default=str),
        json.dumps(a_pre_state, default=str),
    ])
    uuid_hits = _UUID_RE.findall(audit_blob)
    _assert(
        "17: no uuid-shaped raw token appears anywhere in the audit row",
        not uuid_hits,
        detail=("no uuid-shaped value in any audit column"
                if not uuid_hits else f"FOUND={uuid_hits}"),
    )

    # ======================================================================
    # PART 4 -- post-recovery lifecycle.
    # ======================================================================
    print("\n-- PART 4: post-recovery lifecycle --")

    with SessionLocal() as db:
        ws2 = db.query(WeekSettlement).filter_by(league_id=LEAGUE_ID, week=_WEEK).one()
        post_status = ws2.status
        post_settled = ws2.settled
        post_settled_at = ws2.settled_at
        post_token = ws2.recovery_token
        post_ws_count = (
            db.query(WeekSettlement).filter_by(league_id=LEAGUE_ID, week=_WEEK).count()
        )

    _assert(
        "18: week is COMPLETED and settled, with a durable settled_at",
        post_status == "COMPLETED" and post_settled is True and post_settled_at is not None,
        detail=f"status={post_status!r} settled={post_settled} settled_at={post_settled_at}",
    )
    _assert(
        "19: recovery_token cleared by the completion flip (credential retired)",
        post_token is None,
        detail=f"recovery_token={post_token!r}",
    )
    _assert(
        "20: still exactly one week_settlements row (recovery created none)",
        post_ws_count == 1,
        detail=f"row count={post_ws_count}",
    )

    # ======================================================================
    # PART 5 -- exactly-once economics.
    # ======================================================================
    print("\n-- PART 5: exactly-once economics --")

    escrow_a_post = balance_of(f"escrow:{BET_A_ID}")
    escrow_b_post = balance_of(f"escrow:{BET_B_ID}")
    wallet_home_post = balance_of(f"wallet:{HOME_ID}")
    wallet_away_post = balance_of(f"wallet:{AWAY_ID}")

    _assert(
        "21: both escrows drained to zero, exactly once",
        escrow_a_post == 0 and escrow_b_post == 0,
        detail=f"escrow:{BET_A_ID}={escrow_a_post}c escrow:{BET_B_ID}={escrow_b_post}c",
    )
    _assert(
        "22: winner wallet credited the EXACT combined escrow sum",
        wallet_home_post == wallet_home_before + COMBINED_CENTS,
        detail=f"{wallet_home_before}c -> {wallet_home_post}c "
               f"(delta={wallet_home_post - wallet_home_before}c, "
               f"required={COMBINED_CENTS}c = {STAKE_A_CENTS}c + {STAKE_B_CENTS}c)",
    )
    _assert(
        "23: loser wallet received nothing",
        wallet_away_post == wallet_away_before,
        detail=f"{wallet_away_before}c -> {wallet_away_post}c",
    )

    with SessionLocal() as db:
        settled_entries = (
            db.query(LedgerEntry).filter(LedgerEntry.door == "wager_settled").count()
        )
        bets_post = {
            b.id: b.status for b in
            db.query(Bet).filter(Bet.id.in_([BET_A_ID, BET_B_ID])).all()
        }
        tx_rows = db.query(Transaction).all()
        tx_count = len(tx_rows)
        tx_by_wallet = {t.wallet_id: round(t.amount, 2) for t in tx_rows}

    _assert(
        "24: exactly three wager_settled entries (one joint 3-leg posting, no duplicate)",
        settled_entries == 3,
        detail=f"wager_settled count={settled_entries} "
               f"(6 would mean the week settled twice)",
    )
    _assert(
        "25: winner bet won, loser bet lost",
        bets_post.get(BET_A_ID) == "won" and bets_post.get(BET_B_ID) == "lost",
        detail=f"A={bets_post.get(BET_A_ID)!r} B={bets_post.get(BET_B_ID)!r}",
    )
    # Same two-row journal 6d-3 discovered: winner combined credit, loser own stake.
    _assert(
        "26: two payout Transaction rows, winner combined credit and loser stake debit",
        tx_count == 2
        and tx_by_wallet.get(WALLET_HOME_ID) == round(COMBINED_CENTS / 100, 2)
        and tx_by_wallet.get(WALLET_AWAY_ID) == round(-STAKE_B, 2),
        detail=f"count={tx_count} by_wallet={tx_by_wallet} "
               f"expected winner={round(COMBINED_CENTS / 100, 2)} "
               f"loser={round(-STAKE_B, 2)}",
    )
    _assert(
        "27: trial balance is exactly zero after the recovered settlement",
        trial_balance() == 0,
        detail=f"trial_balance={trial_balance()}c",
    )
    # Independent corroboration: the returned report and the ledger are separate
    # surfaces and must agree on how many bets settled.
    _assert(
        "28: returned SettlementReport agrees with the ledger on bets settled",
        getattr(report, "total_bets", None) == 2,
        detail=f"report.total_bets={getattr(report, 'total_bets', '<absent>')} "
               f"expected=2; report={report!r}",
    )

    # ======================================================================
    # PART 6 -- post-completion refusals.
    # ======================================================================
    print("\n-- PART 6: post-completion refusals --")

    second_recover_error = None
    with SessionLocal() as db:
        try:
            recover_week(
                _WEEK, db,
                league_id=LEAGUE_ID,
                actor=ACTOR,
                exit_evidence=VALID_EVIDENCE,
            )
        except Exception as exc:  # noqa: BLE001
            second_recover_error = exc

    _assert(
        "29: a second recover_week refuses the now-COMPLETED week",
        second_recover_error is not None
        and "COMPLETED" in str(second_recover_error),
        detail=(f"raised {type(second_recover_error).__name__}: {second_recover_error}"
                if second_recover_error is not None
                else "nothing raised -- a settled week was accepted for recovery"),
    )

    snap_before = {
        "escrow_a": balance_of(f"escrow:{BET_A_ID}"),
        "escrow_b": balance_of(f"escrow:{BET_B_ID}"),
        "wallet_home": balance_of(f"wallet:{HOME_ID}"),
        "wallet_away": balance_of(f"wallet:{AWAY_ID}"),
        "trial": trial_balance(),
    }
    with SessionLocal() as db:
        snap_before["wager_settled"] = (
            db.query(LedgerEntry).filter(LedgerEntry.door == "wager_settled").count()
        )
        snap_before["ledger_total"] = db.query(LedgerEntry).count()
        snap_before["tx_count"] = db.query(Transaction).count()
        snap_before["audit_count"] = db.query(SettlementRecoveryAudit).count()

    retry_error = None
    retry_report = None
    with SessionLocal() as db:
        try:
            retry_report = settle_week(_WEEK, db, league_id=LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001
            retry_error = exc

    _assert(
        "30: plain settle_week retry is the idempotent no-op, raises nothing",
        retry_error is None,
        detail=(f"returned {type(retry_report).__name__}"
                if retry_error is None
                else f"raised {type(retry_error).__name__}: {retry_error}"),
    )

    with SessionLocal() as db:
        ws3 = db.query(WeekSettlement).filter_by(league_id=LEAGUE_ID, week=_WEEK).one()
        retry_settled_at = ws3.settled_at

    _assert(
        "31: settled_at is the IDENTICAL timestamp after the retry (no re-stamp)",
        retry_settled_at == post_settled_at,
        detail=f"after recovery={post_settled_at} after retry={retry_settled_at}",
    )

    snap_after = {
        "escrow_a": balance_of(f"escrow:{BET_A_ID}"),
        "escrow_b": balance_of(f"escrow:{BET_B_ID}"),
        "wallet_home": balance_of(f"wallet:{HOME_ID}"),
        "wallet_away": balance_of(f"wallet:{AWAY_ID}"),
        "trial": trial_balance(),
    }
    with SessionLocal() as db:
        snap_after["wager_settled"] = (
            db.query(LedgerEntry).filter(LedgerEntry.door == "wager_settled").count()
        )
        snap_after["ledger_total"] = db.query(LedgerEntry).count()
        snap_after["tx_count"] = db.query(Transaction).count()
        snap_after["audit_count"] = db.query(SettlementRecoveryAudit).count()

    drift = {k: (snap_before[k], snap_after[k])
             for k in snap_before if snap_before[k] != snap_after[k]}
    _assert(
        "32: the refused recovery and the retry together moved nothing "
        "(snapshot identical, audit count unchanged)",
        not drift,
        detail=("all balances, entry counts, transaction and audit counts identical"
                if not drift else f"CHANGED={drift}"),
    )

    # ======================================================================
    # PART 7 -- STEP 5's pending-bet safety gate.
    #
    # SYNTHESIZED PRECONDITION, deliberately. A week carrying a non-pending bet
    # cannot arise naturally -- Phase 2 is atomic, which 6d-2 proved. The gate
    # guards a state that should be impossible, so proving the gate requires
    # manufacturing that state. The mechanism under test is entirely real.
    # ======================================================================
    print("\n-- PART 7: STEP 5 pending-bet safety gate (synthesized precondition) --")

    g = _build_beef_week("gate", add_schedule=False)
    G_LEAGUE_ID = g["league_id"]
    G_BET_A_ID, G_BET_B_ID = g["bet_a_id"], g["bet_b_id"]

    g_proc = run_settle_week_crashing(_WEEK, G_LEAGUE_ID, PRE_LOCK)
    g_crashed, g_detail = assert_crashed(g_proc)

    _assert(
        "33: second league's week crashed post-claim, pre-lock (CLAIMED, untouched)",
        g_crashed,
        detail=g_detail,
    )

    # Manufacture the impossible state: one bet already settled.
    with SessionLocal() as db:
        db.query(Bet).filter(Bet.id == G_BET_A_ID).update(
            {"status": "won"}, synchronize_session=False
        )
        db.commit()

    g_escrow_a_before = balance_of(f"escrow:{G_BET_A_ID}")
    g_escrow_b_before = balance_of(f"escrow:{G_BET_B_ID}")

    gate_error = None
    with SessionLocal() as db:
        try:
            recover_week(
                _WEEK, db,
                league_id=G_LEAGUE_ID,
                actor="fr87-6d5a-gate-operator",
                exit_evidence={"category": "process_exit",
                               "detail": "6d-5a STEP 5 gate probe"},
            )
        except Exception as exc:  # noqa: BLE001
            gate_error = exc

    _assert(
        "34: STEP 5 refuses a week with a non-pending bet as "
        "not cleanly recoverable",
        gate_error is not None
        and "not cleanly recoverable" in str(gate_error),
        detail=(f"raised {type(gate_error).__name__}: {gate_error}"
                if gate_error is not None
                else "nothing raised -- the gate admitted a partially settled week"),
    )

    with SessionLocal() as db:
        g_audit_count = (
            db.query(SettlementRecoveryAudit)
            .filter_by(league_id=G_LEAGUE_ID, week=_WEEK)
            .count()
        )
        g_ws = db.query(WeekSettlement).filter_by(
            league_id=G_LEAGUE_ID, week=_WEEK
        ).one()
        g_status, g_token = g_ws.status, g_ws.recovery_token

    _assert(
        "35: the gate refusal wrote no audit row and minted no token",
        g_audit_count == 0 and g_status == "CLAIMED" and g_token is None,
        detail=f"audit rows={g_audit_count} status={g_status!r} token={g_token!r} "
               f"(a pre-STEP-8 abort must roll back both)",
    )
    _assert(
        "36: the gate refusal moved no money, trial balance still zero",
        balance_of(f"escrow:{G_BET_A_ID}") == g_escrow_a_before
        and balance_of(f"escrow:{G_BET_B_ID}") == g_escrow_b_before
        and trial_balance() == 0,
        detail=f"escrow A={balance_of(f'escrow:{G_BET_A_ID}')}c "
               f"escrow B={balance_of(f'escrow:{G_BET_B_ID}')}c "
               f"trial={trial_balance()}c",
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
    print("RESULT: all 6d-5a recovery-authority assertions PASSED")
