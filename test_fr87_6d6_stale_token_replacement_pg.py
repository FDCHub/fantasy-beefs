"""
test_fr87_6d6_stale_token_replacement_pg.py -- FR-8.7 test 6d-6 (PostgreSQL).

SCENARIO. A recovery that dies between STEP 8's commit and STEP 9's settlement,
twice, and then the week settled once by the surviving credential.

6d-5a could not reach this state. Its recovery SUCCEEDED, and a successful
recover_week never leaves a live token behind: STEP 7 mints it, the UPDATE at
1042 writes it under the lock, STEP 9 hands it to settle_week, and the COMPLETED
flip clears it. A committed token on a still-CLAIMED row exists only when a
recovery dies in the window between 1057 and 1062. That window is exactly
POST_RECOVERY_AUTH_COMMIT, and this suite is the first consumer of
run_recover_week_crashing.

WHAT THAT UNLOCKS -- THE TWO OBLIGATIONS 6d-5a RECORDED AND DEFERRED.

  1. FINGERPRINT CORRESPONDENCE. 6d-5a assertion 9 could only prove a
     SHA-256-SHAPED digest was stored, because the raw token was gone by the
     time the assertions ran. Here the token survives on the row, so
     assertions 10 and 21 compute sha256(token) themselves and require exact
     equality with the stored fingerprint. Shape becomes correspondence.

  2. THE NORMAL CALLER MEETING A LIVE TOKEN. 6d-5a explicitly deferred frozen
     6d-5's "normal caller with a live token present is rejected" leg to 6d-6,
     where the state is the natural durable outcome rather than something a
     suite has to manufacture with hand-written SQL. Phase D is that leg, and
     it is reached with no synthesized state whatsoever.

STALE-TOKEN REPLACEMENT IS THE SPINE. Phase C runs the identical recovery a
second time against a row that already carries Phase B's live token. The
overwrite at 1042 is documented at 1040-1041 as handling exactly this -- "a
stale token is simply replaced" -- and prior_recovery_token_present records that
it happened. Phase B writes that flag False; Phase C writes it True. Then the
STALE credential (token1) is refused and the CURRENT one (token2) is admitted.

Sequential 6d-6 covers pre-lock no-token and stale-token refusal. It does
not cover the post-FOR UPDATE revalidation guards' refusal branches; those
require concurrent state change between the pre-lock read and the locked
re-read. Phase E passes through the revalidation at 484-490 on its admit
branch only.

TWO AUTHORIZATIONS, ONE PAYOUT. The economic claim of this suite is that audit
multiplicity does not imply economic multiplicity. Two audit rows and two minted
tokens exist; exactly one wager_settled posting is ever written, and each bet's
escrow is closed exactly once. Assertions 40 and 41 count postings and legs.

WHY NO ASSERTION READS A PAYOUT MAGNITUDE. The fixture is the siblings' $25 /
$40 at 2.60 shape, reused deliberately so the three suites cannot drift. That
shape cannot discriminate between a payout computed from the ACTUAL COMBINED
ESCROW and one computed as amount * odds: 25 + 40 and 25 * 2.60 both give 65.00.
6d-5a's assertion 22 reads that magnitude and is sound there only because its
sibling context pins the intent. Here it would be an assertion that passes under
two different implementations, so no magnitude is read anywhere in this file.
Exactly-once is proven by COUNTS -- postings, legs, audit rows -- and by escrow
accounts reaching zero, never by an amount.

WHY THE PADDED ACTOR AND EVIDENCE. recover_week normalizes actor at 883 and
category/detail at 894-895 and records the STRIPPED values. The crash harness
validates against the stripped form but transports the RAW value, so that
normalization is genuinely exercised across a process boundary rather than
handed input that was already clean. Phases B and C send leading and trailing
whitespace on all three; assertions 11 and 12 require the stripped forms in the
audit row.

THE CONTROL PAIR, STATED PRECISELY. Assertions 7/18 and 9/20 read
prior_recovery_token_present (a column) and observed_pre_state
["prior_token_present"] (a JSON key). Both are written from one variable
computed once at settlement_engine.py:953. They prove that single value
persisted into two destinations, False after Phase B and True after Phase C.
They are NOT independent corroboration of each other and are not described as
such. All four use `is False` / `is True` identity checks, matching 6d-5a lines
475 and 526, so a None from a missing column or absent key fails rather than
silently passing a truthiness test.

OBSERVED VERSUS INFERRED.

  Directly observed:
    - both children's exit codes and crash markers
    - every durable row, token, audit row and balance, read back on fresh
      sessions after the owning process died
    - that sha256 of each surviving token equals its stored fingerprint
    - both Phase D refusals, with their message text
    - that Phase E completes and clears the token

  Inferred, not observed:
    - that Phase C's overwrite is the statement at 1042 specifically, rather
      than some other write. Inferred from prior_recovery_token_present being
      True and the token changing, not from watching that UPDATE execute.

ASSERTIONS (44, labelled 0-43) across five phases:

    Phase A   0-3    crashed settle_week leaves a recoverable, tokenless week
    Phase B   4-12   first recovery authorized and durable, flag False
    Phase C  13-21   second recovery replaces the stale token, flag True
    No-leak  22-25   neither raw token reached the audit's textual surfaces
    Phase D  26-34   no token and stale token both refused, nothing moved
    Phase E  35-42   current token admitted, week settles exactly once
    Closing     43   ledger integrity

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
    print(f"\n[HARNESS ERROR] FR-8.7 6d-6 suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []

# uuid4 string form: 8-4-4-4-12 hex, dash separated. Both minted tokens are
# uuid4 strings, so this catches a leak of either one even if the exact value
# were transformed in some way that defeats a plain substring search.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection begins
    the instant setup succeeds."""
    import hashlib
    import json
    from datetime import datetime, timedelta, timezone

    from db.schema import (
        SessionLocal,
        League, Team, Matchup, NflSchedule, Wallet, Bet,
        BeefChallenge, WeekSettlement, SettlementRecoveryAudit,
    )
    from ledger.ledger import post as ledger_post, balance_of, trial_balance, LedgerEntry
    from betting.settlement_engine import settle_week
    from betting.per_bet_lock import LOCK_SEASON
    from config import CURRENT_SEASON as SEASON

    from test_support_crash import (
        run_settle_week_crashing, run_recover_week_crashing, assert_crashed,
        PRE_LOCK, POST_RECOVERY_AUTH_COMMIT,
    )

    FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)
    _WEEK = 1

    # Identical construction to 6d-2, 6d-3 and 6d-5a. Unequal on both axes.
    HOME_SCORE = 120.5
    AWAY_SCORE = 98.0
    STAKE_A = 25.00
    STAKE_B = 40.00
    STAKE_A_CENTS = int(round(STAKE_A * 100))
    STAKE_B_CENTS = int(round(STAKE_B * 100))

    FUND_CENTS = 20_000
    WALLET_BALANCE_SEED = 500.00

    # Deliberately padded. The harness validates against the stripped form and
    # transports these RAW, so recover_week's own normalization at 883/894-895
    # is what produces the stripped values the audit assertions require.
    ACTOR_RAW = "  fr87-6d6-operator  "
    CATEGORY_RAW = "  process_exit  "
    DETAIL_RAW = "  FR-8.7 6d-6 POST_RECOVERY_AUTH_COMMIT injected crash  "
    ACTOR_STRIPPED = ACTOR_RAW.strip()
    CATEGORY_STRIPPED = CATEGORY_RAW.strip()
    DETAIL_STRIPPED = DETAIL_RAW.strip()
    EVIDENCE_RAW = {"category": CATEGORY_RAW, "detail": DETAIL_RAW}

    # ----------------------------------------------------------------------
    # Fixture builder. Same shape as 6d-5a's so the suites cannot drift apart.
    # ----------------------------------------------------------------------
    def _build_beef_week(label: str) -> dict:
        with SessionLocal() as _db:
            league = League(season=SEASON, name=f"FR-8.7 6d-6 {label}",
                            projection_source="fantasypros")
            _db.add(league)
            _db.commit()
            league_id = league.id

        with SessionLocal() as _db:
            home = Team(league_id=league_id, team_name=f"{label} Home",
                        owner=f"home-{label}", email=f"home@{label}.6d6.test")
            away = Team(league_id=league_id, team_name=f"{label} Away",
                        owner=f"away-{label}", email=f"away@{label}.6d6.test")
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
                        home_score=HOME_SCORE, away_score=AWAY_SCORE,
                        # S6 §8 — a COMPLETED week, stated explicitly.
                        finalized_at=_FIXTURE_FINAL_AT)
            _db.add(m)
            # NflSchedule is keyed on (season, week), not league. One row only.
            _db.add(NflSchedule(season=LOCK_SEASON, week=_WEEK,
                                home_team="KC", away_team="PHI",
                                kickoff_utc=FUTURE_KO))
            _db.commit()
            matchup_id = m.id

        with SessionLocal() as _db:
            bet_a = Bet(matchup_id=matchup_id, wallet_id=wallet_home_id,
                        picked_team_id=home_id, bet_type="straight",
                        amount=STAKE_A, odds=2.60, status="pending",
                        description=f"6d-6 {label} challenger (HOME, wins)")
            bet_b = Bet(matchup_id=matchup_id, wallet_id=wallet_away_id,
                        picked_team_id=away_id, bet_type="straight",
                        amount=STAKE_B, odds=1.625, status="pending",
                        description=f"6d-6 {label} challenged (AWAY, loses)")
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

    f = _build_beef_week("primary")
    LEAGUE_ID = f["league_id"]
    BET_A_ID, BET_B_ID = f["bet_a_id"], f["bet_b_id"]

    # ----------------------------------------------------------------------
    # Readers. Each opens a FRESH session, so every value asserted below is
    # durable committed state read after the owning process died.
    # ----------------------------------------------------------------------
    def _read_ws() -> dict:
        with SessionLocal() as _db:
            ws = (_db.query(WeekSettlement)
                  .filter_by(league_id=LEAGUE_ID, week=_WEEK).one_or_none())
            return {
                "status":     getattr(ws, "status", None),
                "settled":    getattr(ws, "settled", None),
                "settled_at": getattr(ws, "settled_at", None),
                "token":      getattr(ws, "recovery_token", None),
            }

    def _read_audits() -> list[dict]:
        with SessionLocal() as _db:
            rows = (_db.query(SettlementRecoveryAudit)
                    .filter_by(league_id=LEAGUE_ID, week=_WEEK)
                    .order_by(SettlementRecoveryAudit.id)
                    .all())
            return [{
                "id":            r.id,
                "actor":         r.actor,
                "fingerprint":   r.recovery_token_fingerprint,
                "prior_present": r.prior_recovery_token_present,
                "exit_evidence": dict(r.exit_evidence or {}),
                "pre_state":     dict(r.observed_pre_state or {}),
            } for r in rows]

    def _credential_surfaces(a: dict) -> str:
        """Serialize the four TEXTUAL, CREDENTIAL-BEARING surfaces of one audit
        row: actor, exit_evidence, observed_pre_state, recovery_token_fingerprint.

        Scope, stated exactly: these are the fields capable of carrying a token.
        This is NOT a scan of every column on the row -- id, league_id, week and
        recovered_at are not included and are not claimed to be covered."""
        return " | ".join([
            str(a["actor"]),
            json.dumps(a["exit_evidence"], default=str),
            json.dumps(a["pre_state"], default=str),
            str(a["fingerprint"]),
        ])

    # ======================================================================
    # PHASE A -- a crashed normal settlement leaves a recoverable, tokenless
    # week. This is 6d-1's durable outcome, reproduced as the starting state.
    # ======================================================================
    print("\n-- PHASE A: crashed settle_week leaves a recoverable week --")

    proc_a = run_settle_week_crashing(_WEEK, LEAGUE_ID, PRE_LOCK)
    a_crashed, a_detail = assert_crashed(proc_a)

    ws_a = _read_ws()
    audits_a = _read_audits()

    _assert(
        "0: week is CLAIMED after the crashed normal settlement",
        ws_a["status"] == "CLAIMED",
        detail=f"status={ws_a['status']!r}; child {a_detail}"
               f"{'' if a_crashed else ' [CHILD DID NOT CRASH BY INJECTION]'}",
    )
    _assert(
        "1: week is unsettled with no completion timestamp",
        ws_a["settled"] is False and ws_a["settled_at"] is None,
        detail=f"settled={ws_a['settled']} settled_at={ws_a['settled_at']}",
    )
    _assert(
        "2: no recovery_token on the row (nothing has authorized a recovery)",
        ws_a["token"] is None,
        detail=f"recovery_token={ws_a['token']!r}",
    )
    _assert(
        "3: no audit rows exist yet",
        len(audits_a) == 0,
        detail=f"audit row count={len(audits_a)}",
    )

    # ======================================================================
    # PHASE B -- first authorized recovery, killed in the 1057->1062 window.
    # The authorization is durable; the settlement it authorized never starts.
    # ======================================================================
    print("\n-- PHASE B: first recovery dies after its authorization commit --")

    proc_b = run_recover_week_crashing(
        _WEEK, LEAGUE_ID, POST_RECOVERY_AUTH_COMMIT,
        ACTOR_RAW, dict(EVIDENCE_RAW),
    )
    b_crashed, b_detail = assert_crashed(proc_b)

    ws_b = _read_ws()
    audits_b = _read_audits()
    token1 = ws_b["token"]
    audit1 = audits_b[0] if audits_b else {}

    _assert(
        "4: week is still CLAIMED (STEP 9's settlement never ran)",
        ws_b["status"] == "CLAIMED",
        detail=f"status={ws_b['status']!r}; child {b_detail}"
               f"{'' if b_crashed else ' [CHILD DID NOT CRASH BY INJECTION]'}",
    )
    _assert(
        "5: a recovery_token is durably present on the still-CLAIMED row",
        token1 is not None,
        detail=f"token1 present={token1 is not None} "
               f"len={len(token1) if isinstance(token1, str) else 'n/a'}",
    )
    _assert(
        "6: exactly one audit row for this authorization",
        len(audits_b) == 1,
        detail=f"audit row count={len(audits_b)}",
    )
    _assert(
        "7: prior_recovery_token_present is False on the first authorization",
        audit1.get("prior_present") is False,
        detail=f"prior_recovery_token_present={audit1.get('prior_present')!r} "
               f"(row token before this recovery was {ws_a['token']!r})",
    )
    _assert(
        "8: observed_pre_state carries a prior_token_present key",
        "prior_token_present" in audit1.get("pre_state", {}),
        detail=f"pre_state keys={sorted(audit1.get('pre_state', {}).keys())}",
    )
    _assert(
        "9: observed_pre_state.prior_token_present is False",
        audit1.get("pre_state", {}).get("prior_token_present") is False,
        detail=f"prior_token_present="
               f"{audit1.get('pre_state', {}).get('prior_token_present')!r}",
    )
    _assert(
        "10: stored fingerprint is exactly sha256 of the surviving token1",
        isinstance(token1, str)
        and hashlib.sha256(token1.encode()).hexdigest() == audit1.get("fingerprint"),
        detail=f"stored={audit1.get('fingerprint')!r} "
               f"computed={hashlib.sha256(token1.encode()).hexdigest()!r}"
               if isinstance(token1, str) else "token1 is not a string",
    )
    _assert(
        "11: actor recorded stripped, not as the padded value transported",
        audit1.get("actor") == ACTOR_STRIPPED and audit1.get("actor") != ACTOR_RAW,
        detail=f"recorded={audit1.get('actor')!r} stripped={ACTOR_STRIPPED!r} "
               f"sent={ACTOR_RAW!r}",
    )
    _assert(
        "12: exit_evidence category and detail recorded stripped",
        audit1.get("exit_evidence", {}).get("category") == CATEGORY_STRIPPED
        and audit1.get("exit_evidence", {}).get("detail") == DETAIL_STRIPPED,
        detail=f"category={audit1.get('exit_evidence', {}).get('category')!r} "
               f"detail={audit1.get('exit_evidence', {}).get('detail')!r} "
               f"(sent padded)",
    )

    # ======================================================================
    # PHASE C -- identical recovery against a row that already carries a live
    # token. The overwrite at 1042 replaces the stale credential; the flag
    # records that it happened.
    # ======================================================================
    print("\n-- PHASE C: second recovery replaces the stale token --")

    proc_c = run_recover_week_crashing(
        _WEEK, LEAGUE_ID, POST_RECOVERY_AUTH_COMMIT,
        ACTOR_RAW, dict(EVIDENCE_RAW),
    )
    c_crashed, c_detail = assert_crashed(proc_c)

    ws_c = _read_ws()
    audits_c = _read_audits()
    token2 = ws_c["token"]
    audit2 = audits_c[1] if len(audits_c) > 1 else {}

    escrow_a_c = balance_of(f"escrow:{BET_A_ID}")
    escrow_b_c = balance_of(f"escrow:{BET_B_ID}")

    _assert(
        "13: week is still CLAIMED after the second authorization",
        ws_c["status"] == "CLAIMED",
        detail=f"status={ws_c['status']!r}; child {c_detail}"
               f"{'' if c_crashed else ' [CHILD DID NOT CRASH BY INJECTION]'}",
    )
    _assert(
        "14: a recovery_token is still durably present",
        token2 is not None,
        detail=f"token2 present={token2 is not None} "
               f"len={len(token2) if isinstance(token2, str) else 'n/a'}",
    )
    _assert(
        "15: the second token is a DIFFERENT credential from the first",
        token2 != token1,
        detail="token2 differs from token1"
               if token2 != token1 else "token2 == token1 (no replacement)",
    )
    _assert(
        "16: the row carries token2, the freshly minted credential",
        ws_c["token"] == token2,
        detail=f"row token is token2={ws_c['token'] == token2} "
               f"(is token1={ws_c['token'] == token1})",
    )
    _assert(
        "17: exactly two append-only audit rows, ordered by id ascending",
        len(audits_c) == 2
        and audits_c[0]["id"] == audit1.get("id")
        and audits_c[1]["id"] > audits_c[0]["id"],
        detail=f"count={len(audits_c)} ids={[a['id'] for a in audits_c]}",
    )
    _assert(
        "18: prior_recovery_token_present is True on the second authorization",
        audit2.get("prior_present") is True,
        detail=f"prior_recovery_token_present={audit2.get('prior_present')!r} "
               f"(a stale token was on the row and was replaced)",
    )
    _assert(
        "19: the second audit's observed_pre_state carries prior_token_present",
        "prior_token_present" in audit2.get("pre_state", {}),
        detail=f"pre_state keys={sorted(audit2.get('pre_state', {}).keys())}",
    )
    _assert(
        "20: the second observed_pre_state.prior_token_present is True",
        audit2.get("pre_state", {}).get("prior_token_present") is True,
        detail=f"prior_token_present="
               f"{audit2.get('pre_state', {}).get('prior_token_present')!r}",
    )
    _assert(
        "21: second stored fingerprint is exactly sha256 of the surviving token2",
        isinstance(token2, str)
        and hashlib.sha256(token2.encode()).hexdigest() == audit2.get("fingerprint"),
        detail=f"stored={audit2.get('fingerprint')!r} "
               f"computed={hashlib.sha256(token2.encode()).hexdigest()!r}"
               if isinstance(token2, str) else "token2 is not a string",
    )

    # ======================================================================
    # NO-LEAK -- neither raw credential reached the audit's textual surfaces.
    # Scope is the four credential-bearing fields only, not the whole row.
    # ======================================================================
    print("\n-- NO-LEAK: neither raw token reached the audit's textual surfaces --")

    surfaces1 = _credential_surfaces(audit1) if audit1 else ""
    surfaces2 = _credential_surfaces(audit2) if audit2 else ""
    uuid_hits1 = _UUID_RE.findall(surfaces1)
    uuid_hits2 = _UUID_RE.findall(surfaces2)

    # HARD PRECONDITION, deliberately not an _assert. Every condition below is
    # satisfied by an EMPTY string: `token not in ""` is True and findall("")
    # is []. So if serialization produced nothing -- a missing audit row makes
    # the ternaries above yield "" -- all four would print [PASS] and the suite
    # would certify a no-leak result having scanned zero characters. An _assert
    # here would merely add a 45th label; this must abort the run instead.
    if not surfaces1 or not surfaces2:
        raise RuntimeError(
            "6d-6 precondition failed: credential-surface serialization is "
            f"empty (len surfaces1={len(surfaces1)}, len surfaces2="
            f"{len(surfaces2)}). Assertions 22-25 pass vacuously against an "
            "empty string and would certify no-leak while scanning nothing. "
            "Refusing to report a green no-leak result."
        )

    _assert(
        "22: token1 does not appear in the first audit's credential surfaces",
        isinstance(token1, str) and token1 not in surfaces1,
        detail=(f"token1 absent from actor / exit_evidence / observed_pre_state "
                f"/ fingerprint; scanned {len(surfaces1)} chars"
                if isinstance(token1, str) and token1 not in surfaces1
                else f"TOKEN1 FOUND in a scanned surface "
                     f"({len(surfaces1)} chars scanned)"),
    )
    _assert(
        "23: token2 does not appear in the second audit's credential surfaces",
        isinstance(token2, str) and token2 not in surfaces2,
        detail=(f"token2 absent from actor / exit_evidence / observed_pre_state "
                f"/ fingerprint; scanned {len(surfaces2)} chars"
                if isinstance(token2, str) and token2 not in surfaces2
                else f"TOKEN2 FOUND in a scanned surface "
                     f"({len(surfaces2)} chars scanned)"),
    )
    _assert(
        "24: no uuid-shaped value in the first audit's credential surfaces",
        not uuid_hits1,
        detail="no uuid-shaped substring in the four scanned fields"
               if not uuid_hits1 else f"FOUND={uuid_hits1}",
    )
    _assert(
        "25: no uuid-shaped value in the second audit's credential surfaces",
        not uuid_hits2,
        detail="no uuid-shaped substring in the four scanned fields"
               if not uuid_hits2 else f"FOUND={uuid_hits2}",
    )

    # ======================================================================
    # PHASE D -- the two pre-lock refusals, reached with no synthesized state.
    #
    # Sequential 6d-6 covers pre-lock no-token and stale-token refusal. It does
    # not cover the post-FOR UPDATE revalidation guards' refusal branches; those
    # require concurrent state change between the pre-lock read and the locked
    # re-read. Phase E passes through the revalidation at 484-490 on its admit
    # branch only.
    #
    # Both refusals are BARE raises in Phase 1 (settlement_engine.py 397 and
    # 407) -- they fire before the lock exists, so they do not route through
    # _abort_phase2 and nothing rolls back the read snapshot the Phase-1 SELECT
    # opened. The parent session must be rolled back explicitly after each, or
    # every durable read below is served from that stale snapshot.
    # ======================================================================
    print("\n-- PHASE D: no token and stale token are both refused --")

    parent_db = SessionLocal()

    d_no_token_error = None
    try:
        settle_week(_WEEK, parent_db, league_id=LEAGUE_ID)
    except ValueError as exc:
        d_no_token_error = exc

    _assert(
        "26: an ordinary settle_week with no token raises ValueError",
        isinstance(d_no_token_error, ValueError),
        detail=f"raised {type(d_no_token_error).__name__}"
               if d_no_token_error is not None else "did not raise",
    )
    _assert(
        "27: that refusal names the missing recovery_token",
        "no recovery_token was supplied" in str(d_no_token_error or ""),
        detail=f"message={str(d_no_token_error or '')!r}",
    )

    parent_db.rollback()

    d_stale_error = None
    try:
        settle_week(_WEEK, parent_db, league_id=LEAGUE_ID, recovery_token=token1)
    except ValueError as exc:
        d_stale_error = exc

    _assert(
        "28: settle_week with the STALE token1 raises ValueError",
        isinstance(d_stale_error, ValueError),
        detail=f"raised {type(d_stale_error).__name__}"
               if d_stale_error is not None else "did not raise",
    )
    _assert(
        "29: that refusal names the token mismatch",
        "does not match the row's token" in str(d_stale_error or ""),
        detail=f"message={str(d_stale_error or '')!r}",
    )

    parent_db.rollback()

    d_ws = (parent_db.query(WeekSettlement)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK).one())
    d_status = d_ws.status
    d_token = d_ws.recovery_token
    d_audit_count = (parent_db.query(SettlementRecoveryAudit)
                     .filter_by(league_id=LEAGUE_ID, week=_WEEK).count())
    parent_db.close()

    d_trial = trial_balance()
    d_escrow_a = balance_of(f"escrow:{BET_A_ID}")
    d_escrow_b = balance_of(f"escrow:{BET_B_ID}")

    _assert(
        "30: the week is still CLAIMED after both refusals",
        d_status == "CLAIMED",
        detail=f"status={d_status!r}",
    )
    _assert(
        "31: the row still carries token2, untouched by either refusal",
        d_token == token2,
        detail=f"row token is token2={d_token == token2} "
               f"(is token1={d_token == token1})",
    )
    _assert(
        "32: still exactly two audit rows (a refusal authorizes nothing)",
        d_audit_count == 2,
        detail=f"audit row count={d_audit_count}",
    )
    _assert(
        "33: trial balance is exactly zero after both refusals",
        d_trial == 0,
        detail=f"trial_balance={d_trial}c",
    )
    _assert(
        "34: both escrows still at their Phase-C balances (no money moved)",
        d_escrow_a == escrow_a_c and d_escrow_b == escrow_b_c,
        detail=f"escrow:{BET_A_ID}={d_escrow_a}c (phase C {escrow_a_c}c) "
               f"escrow:{BET_B_ID}={d_escrow_b}c (phase C {escrow_b_c}c)",
    )

    # ======================================================================
    # PHASE E -- the CURRENT credential is admitted and the week settles once.
    # ======================================================================
    print("\n-- PHASE E: the current token is admitted and settles the week --")

    e_error = None
    e_report = None
    e_db = SessionLocal()
    try:
        e_report = settle_week(_WEEK, e_db, league_id=LEAGUE_ID,
                               recovery_token=token2)
    except Exception as exc:  # noqa: BLE001
        e_error = exc
    e_db.close()

    ws_e = _read_ws()

    with SessionLocal() as db:
        settled_entry_count = (
            db.query(LedgerEntry).filter(LedgerEntry.door == "wager_settled").count()
        )
        escrow_a_legs = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.door == "wager_settled",
                    LedgerEntry.account == f"escrow:{BET_A_ID}")
            .count()
        )
        escrow_b_legs = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.door == "wager_settled",
                    LedgerEntry.account == f"escrow:{BET_B_ID}")
            .count()
        )
        pending_count = (
            db.query(Bet).filter(Bet.id.in_([BET_A_ID, BET_B_ID]),
                                 Bet.status == "pending").count()
        )
        e_audit_count = (
            db.query(SettlementRecoveryAudit)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK).count()
        )

    _assert(
        "35: settle_week with the current token2 returns without raising",
        e_error is None and e_report is not None,
        detail=(f"returned {type(e_report).__name__}" if e_error is None
                else f"raised {type(e_error).__name__}: {e_error}"),
    )
    _assert(
        "36: the week is COMPLETED",
        ws_e["status"] == "COMPLETED",
        detail=f"status={ws_e['status']!r}",
    )
    _assert(
        "37: the week is settled with a durable completion timestamp",
        ws_e["settled"] is True and ws_e["settled_at"] is not None,
        detail=f"settled={ws_e['settled']} settled_at={ws_e['settled_at']}",
    )
    _assert(
        "38: the recovery_token is cleared by the completion flip",
        ws_e["token"] is None,
        detail=f"recovery_token={ws_e['token']!r}",
    )
    _assert(
        "39: no bet remains pending",
        pending_count == 0,
        detail=f"pending bets={pending_count}",
    )
    _assert(
        "40: exactly three wager_settled ledger entries (one 3-leg posting)",
        settled_entry_count == 3,
        detail=f"wager_settled entry count={settled_entry_count} "
               f"(this file builds one fixture; 6 would mean two payouts for "
               f"two authorizations)",
    )
    _assert(
        "41: each bet's escrow was closed exactly once",
        escrow_a_legs == 1 and escrow_b_legs == 1
        and balance_of(f"escrow:{BET_A_ID}") == 0
        and balance_of(f"escrow:{BET_B_ID}") == 0,
        detail=f"escrow:{BET_A_ID} legs={escrow_a_legs} "
               f"balance={balance_of(f'escrow:{BET_A_ID}')}c; "
               f"escrow:{BET_B_ID} legs={escrow_b_legs} "
               f"balance={balance_of(f'escrow:{BET_B_ID}')}c",
    )
    _assert(
        "42: still exactly two audit rows (settling authorized nothing new)",
        e_audit_count == 2,
        detail=f"audit row count={e_audit_count}",
    )

    # ======================================================================
    # CLOSING -- ledger integrity across the whole sequence.
    # ======================================================================
    print("\n-- CLOSING: ledger integrity --")

    final_trial = trial_balance()
    _assert(
        "43: trial balance is exactly zero after the settled week",
        final_trial == 0,
        detail=f"trial_balance={final_trial}c",
    )

    # Derived conclusion, not an assertion: it restates what assertions 17, 40,
    # 41 and 42 already established, and asserting it again would count one
    # fact twice.
    print()
    print("  CONCLUSION: two audit authorizations, one payout set; "
          "recovery-audit multiplicity does not imply economic multiplicity.")


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
    print("RESULT: all 6d-6 stale-token-replacement assertions PASSED")
