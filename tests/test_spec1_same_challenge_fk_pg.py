"""
test_spec1_same_challenge_fk_pg.py — SPEC 1 (Proposal Lifecycle, Rev 3) §3.4:
a challenge's active_proposal_id / accepted_proposal_id must reference a
BeefProposal that belongs to THAT SAME challenge.

This is enforced by two composite foreign keys on beef_challenges:
    (active_proposal_id,   id) -> (beef_proposals.id, beef_proposals.challenge_id)
    (accepted_proposal_id, id) -> (beef_proposals.id, beef_proposals.challenge_id)
binding the referenced proposal's challenge_id to this challenge's id.

WHY POSTGRES-ONLY: the beef_challenges<->beef_proposals pointer cycle forces
use_alter on these FKs, and SQLite silently drops ALTER-added foreign keys (the
same reason challenger_bet_id/challenged_bet_id are unenforced under SQLite). So
the SQLite suite (test_spec1_proposal_lifecycle_red.py, T17) can only assert the
constraint is DECLARED in metadata. Only Postgres actually REJECTS a
cross-challenge pointer, which is what this test proves.

Requires TEST_DATABASE_URL (a dedicated, empty, "_test"-named Postgres DB). The
harness REFUSES to run without it and NEVER falls back to DATABASE_URL.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Harness FIRST — it applies the safety guards, sets DATABASE_URL to the
# disposable test DB, and imports+binds db.schema internally. No project module
# may be imported before this call.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Spec 1 same-challenge FK suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    from datetime import datetime

    from sqlalchemy.exc import IntegrityError

    from db.schema import (
        SessionLocal, BeefChallenge, BeefProposal, League, Team,
    )

    _FUTURE = datetime(2026, 9, 14, 18, 0, 0)

    # ── Fixtures: one league, two teams, two SEPARATE challenges A and B, and one
    #    proposal under each. ────────────────────────────────────────────────────
    with SessionLocal() as db:
        lg = League(season=2026, name="Spec1 FK League", projection_source="fantasypros")
        db.add(lg)
        db.flush()
        ta = Team(league_id=lg.id, team_name="Alpha", owner="Al", email="al@t.com")
        tb = Team(league_id=lg.id, team_name="Bravo", owner="Bo", email="bo@t.com")
        db.add_all([ta, tb])
        db.flush()

        def _mk_challenge():
            c = BeefChallenge(
                challenger_team_id=ta.id, challenged_team_id=tb.id, week=1,
                bet_type="straight", amount=10.0,
                challenger_odds=1.9, challenged_odds=1.9,
                challenger_moneyline=-110, challenged_moneyline=-110,
                expires_at=_FUTURE,
                challenge_mode="locked", wager_type="straight", response_status="offered",
            )
            db.add(c)
            db.flush()
            return c

        chal_a = _mk_challenge()
        chal_b = _mk_challenge()

        prop_a = BeefProposal(challenge_id=chal_a.id, version_number=1,
                              version_kind="initial", proposing_team_id=ta.id)
        prop_b = BeefProposal(challenge_id=chal_b.id, version_number=1,
                              version_kind="initial", proposing_team_id=ta.id)
        db.add_all([prop_a, prop_b])
        db.commit()
        A_ID, B_ID = chal_a.id, chal_b.id
        PROP_A_ID, PROP_B_ID = prop_a.id, prop_b.id

    # ── 0. Legacy shape (both pointers NULL) commits — additive nullability ──────
    with SessionLocal() as db:
        c = db.get(BeefChallenge, A_ID)
        ok = c.active_proposal_id is None and c.accepted_proposal_id is None
        _assert("legacy NULL pointers permitted (MATCH SIMPLE)", ok)

    # ── 1. active_proposal_id -> a proposal of the SAME challenge: accepted ──────
    with SessionLocal() as db:
        c = db.get(BeefChallenge, A_ID)
        c.active_proposal_id = PROP_A_ID
        try:
            db.commit()
            _assert("active_proposal_id accepts a same-challenge proposal", True)
        except IntegrityError as e:
            db.rollback()
            _assert("active_proposal_id accepts a same-challenge proposal", False, str(e).splitlines()[0])

    # ── 2. active_proposal_id -> a proposal of a DIFFERENT challenge: REJECTED ───
    with SessionLocal() as db:
        c = db.get(BeefChallenge, A_ID)
        c.active_proposal_id = PROP_B_ID   # PROP_B belongs to challenge B, not A
        try:
            db.flush()
            _assert("active_proposal_id rejects a cross-challenge proposal", False,
                    "cross-challenge pointer accepted")
            db.rollback()
        except IntegrityError:
            db.rollback()
            _assert("active_proposal_id rejects a cross-challenge proposal", True)

    # ── 3. accepted_proposal_id -> a proposal of the SAME challenge: accepted ────
    with SessionLocal() as db:
        c = db.get(BeefChallenge, A_ID)
        c.accepted_proposal_id = PROP_A_ID
        try:
            db.commit()
            _assert("accepted_proposal_id accepts a same-challenge proposal", True)
        except IntegrityError as e:
            db.rollback()
            _assert("accepted_proposal_id accepts a same-challenge proposal", False, str(e).splitlines()[0])

    # ── 4. accepted_proposal_id -> a proposal of a DIFFERENT challenge: REJECTED ─
    with SessionLocal() as db:
        c = db.get(BeefChallenge, A_ID)
        c.accepted_proposal_id = PROP_B_ID
        try:
            db.flush()
            _assert("accepted_proposal_id rejects a cross-challenge proposal", False,
                    "cross-challenge pointer accepted")
            db.rollback()
        except IntegrityError:
            db.rollback()
            _assert("accepted_proposal_id rejects a cross-challenge proposal", True)

    # ── Summary ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*52}")
    if _failures:
        print(f"FAILED: {len(_failures)} assertion(s)")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All assertions PASSED")


try:
    main(tdb)
finally:
    primary_active = sys.exc_info()[0] is not None
    try:
        tdb.teardown()
    except Exception as teardown_exc:
        print(f"\n[HARNESS ERROR] teardown failed:\n  {teardown_exc}")
        if not primary_active:
            raise
