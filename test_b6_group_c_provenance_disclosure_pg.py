"""
test_b6_group_c_provenance_disclosure_pg.py — B6 Package 3 Group C: provenance
and disclosure schema (PostgreSQL).

SCOPE FENCE. This suite proves Group C ONLY: the nine §4.1 provenance columns
plus §4.2 `self_approved`, the flipped `status` default, the two topup_bet-scoped
CHECK constraints, and the `top_off_disclosure` table per §4.5. It does NOT
exercise the issuance service, the cap, authorization, season close, money
movement or any route — those are Groups D-F and do not exist yet. Nothing here
imports economy/top_off.py, and nothing here calls the ledger or the legacy
wallet writers.

Postgres only. Every assertion below turns on a named CHECK or UNIQUE constraint
firing at COMMIT, and on PostgreSQL reporting WHICH constraint failed. SQLite
raises a generic error without a constraint name, so it would prove the weaker
claim "something was rejected" rather than "the intended rule rejected it".

WHY CONSTRAINT NAMES ARE ASSERTED, NOT JUST IntegrityError. Several of these
rows are illegal for more than one potential reason, and a test that accepted any
IntegrityError would pass even if the constraint under test had been deleted. The
suite therefore reads the violated constraint name out of the driver diagnostics
and asserts it exactly, using the defensive accessor already established in this
codebase at api/main.py:1447 and test_commissioner_genesis_and_grant_pg.py:450.

WHY decision IS NOT NULL IS LOAD-BEARING (scenarios S14-L4..L6). A SQL CHECK
rejects only on a definite FALSE and passes on UNKNOWN. Without the
`decision IS NOT NULL` conjunct in ck_faab_tx_topup_bet_lifecycle, a topup_bet
row carrying decision = NULL evaluates every legal-pair disjunct to NULL, makes
the OR chain NULL, and SILENTLY COMMITS. Those three scenarios fail loudly if the
conjunct is ever removed.

SCENARIOS:
    S13      disclosure_event_id stores and round-trips TopOffDisclosure.event_id
             as a uuid.UUID, and is never the integer disclosure primary key
    S14-A    four legal lifecycle rows commit
    S14-L    six lifecycle-invalid rows rejected by ck_faab_tx_topup_bet_lifecycle
    S14-K    six linkage-invalid rows rejected by ck_faab_tx_topup_bet_linkage
    S14-C    a non-topup_bet row with status='failed' still commits
    C-a      disclosure uniqueness: uq_topoff_disclosure_event_id and
             uq_topoff_disclosure_faab_tx
    C-b      self-approval reason: ck_topoff_disclosure_selfapproval_reason
    C-c      schema shape: columns, named constraints, UUID linkage uniqueness

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — setup_postgres_test_db() applies its guards, sets
# DATABASE_URL to the disposable test DB, and imports+binds db.schema
# INTERNALLY. No project module may be imported before this call.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] B6 Group C provenance suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []

LIFECYCLE_CK = "ck_faab_tx_topup_bet_lifecycle"
LINKAGE_CK   = "ck_faab_tx_topup_bet_linkage"
SELFAPP_CK   = "ck_topoff_disclosure_selfapproval_reason"
UQ_EVENT     = "uq_topoff_disclosure_event_id"
UQ_FAAB_TX   = "uq_topoff_disclosure_faab_tx"


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection
    begins the instant setup succeeds."""
    from datetime import datetime, timezone

    from sqlalchemy import inspect, text
    from sqlalchemy.exc import IntegrityError

    from db.schema import (
        SessionLocal,
        FaabTransaction,
        League,
        Team,
        TopOffDisclosure,
        User,
    )
    import config

    SEASON = config.ALLOCATION_SEASON

    # ── helpers ───────────────────────────────────────────────────────────

    def constraint_of(exc) -> str | None:
        """The PostgreSQL constraint name that rejected the write.

        Defensive two-step getattr, following api/main.py:1447: a driver
        without .diag yields None rather than an AttributeError, so a future
        driver swap degrades into a visible assertion failure instead of an
        unrelated crash inside the test harness.
        """
        return getattr(getattr(exc, "orig", None), "diag", None) and getattr(
            exc.orig.diag, "constraint_name", None
        )

    def seed() -> tuple[int, int, int, int]:
        """league_id, team_id, requester_user_id, approver_user_id."""
        with SessionLocal() as db:
            league = League(season=SEASON, name="Group C Provenance League")
            db.add(league)
            db.flush()
            team = Team(
                league_id = league.id,
                team_name = "Team C",
                owner     = "Owner C",
                email     = f"ownerc_{league.id}@example.test",
            )
            db.add(team)
            db.flush()
            req = User(email=f"req_{league.id}@example.test",
                       hashed_password="x", team_id=team.id, role="gm")
            app_ = User(email=f"app_{league.id}@example.test",
                        hashed_password="x", role="commissioner")
            db.add_all([req, app_])
            db.flush()
            db.commit()
            return league.id, team.id, req.id, app_.id

    def tx_kwargs(league_id, team_id, **over) -> dict:
        """A topup_bet request row. Callers override the fields under test."""
        base = dict(
            league_id = league_id,
            team_id   = team_id,
            type      = "topup_bet",
            amount    = 50.0,
            status    = "pending",
            decision  = "pending",
        )
        base.update(over)
        return base

    def insert_tx(**kwargs) -> tuple[bool, str | None, int | None]:
        """Attempt one FaabTransaction insert in its OWN session, so a refusal
        cannot poison the next attempt. Returns (committed, constraint, id)."""
        with SessionLocal() as db:
            try:
                row = FaabTransaction(**kwargs)
                db.add(row)
                db.commit()
                return True, None, row.id
            except IntegrityError as e:
                db.rollback()
                return False, constraint_of(e), None

    def insert_disclosure(**kwargs) -> tuple[bool, str | None, int | None]:
        with SessionLocal() as db:
            try:
                row = TopOffDisclosure(**kwargs)
                db.add(row)
                db.commit()
                return True, None, row.id
            except IntegrityError as e:
                db.rollback()
                return False, constraint_of(e), None

    def disclosure_kwargs(faab_tx_id, league_id, team_id, req_id, app_id, **over) -> dict:
        base = dict(
            event_id            = uuid.uuid4(),
            faab_transaction_id = faab_tx_id,
            league_id           = league_id,
            season              = SEASON,
            team_id             = team_id,
            amount_cents        = 5000,
            requester_user_id   = req_id,
            decided_by_user_id  = app_id,
            self_approved       = False,
            decision_reason     = None,
            decided_at          = datetime.now(timezone.utc),
            ledger_posting_id   = uuid.uuid4(),
        )
        base.update(over)
        return base

    # ══ S13 ═══════════════════════════════════════════════════════════════
    #
    # disclosure_event_id must carry the disclosure's UUID event_id — NOT its
    # integer primary key. Storing the PK would look correct in any single-row
    # test (both are "the disclosure") and would silently break the §4.7
    # provenance chain the first time the two diverged.
    print("\nS13 — disclosure_event_id stores and round-trips the UUID event_id")
    tdb.reset()
    league_id, team_id, req_id, app_id = seed()

    ev_id      = uuid.uuid4()
    posting_id = uuid.uuid4()

    ok, ck, tx_id = insert_tx(**tx_kwargs(
        league_id, team_id,
        decision            = "approved",
        status              = "applied",
        ledger_posting_id   = posting_id,
        disclosure_event_id = ev_id,
        amount_cents        = 5000,
        season              = SEASON,
        requester_user_id   = req_id,
        decided_by_user_id  = app_id,
        self_approved       = False,
    ))
    _assert("S13 the approved/applied request row committed", ok, f"constraint={ck}")

    d_ok, d_ck, disc_pk = insert_disclosure(**disclosure_kwargs(
        tx_id, league_id, team_id, req_id, app_id,
        event_id          = ev_id,
        ledger_posting_id = posting_id,
    ))
    _assert("S13 the disclosure row committed", d_ok, f"constraint={d_ck}")

    with SessionLocal() as db:
        tx   = db.query(FaabTransaction).filter(FaabTransaction.id == tx_id).one()
        disc = db.query(TopOffDisclosure).filter(TopOffDisclosure.id == disc_pk).one()
        round_tripped = tx.disclosure_event_id
        disc_event    = disc.event_id
        disc_int_pk   = disc.id

    _assert("S13 disclosure_event_id round-trips as a uuid.UUID",
            isinstance(round_tripped, uuid.UUID), f"got {type(round_tripped).__name__}")
    _assert("S13 it equals TopOffDisclosure.event_id",
            round_tripped == disc_event, f"{round_tripped} vs {disc_event}")
    _assert("S13 it equals the UUID that was written",
            round_tripped == ev_id, f"{round_tripped} vs {ev_id}")
    _assert("S13 it is NOT the integer disclosure primary key",
            round_tripped != disc_int_pk, f"pk={disc_int_pk}")
    _assert("S13 it is not even the same TYPE as the integer primary key",
            not isinstance(round_tripped, int), f"pk type={type(disc_int_pk).__name__}")
    _assert("S13 the disclosure primary key really is an int (so the check is meaningful)",
            isinstance(disc_int_pk, int), f"got {type(disc_int_pk).__name__}")

    # ══ S14-A — legal lifecycle rows commit ═══════════════════════════════
    print("\nS14-A — the four legal decision/status pairs commit")
    tdb.reset()
    league_id, team_id, req_id, app_id = seed()

    legal = [
        ("pending/pending, no linkage",     dict(decision="pending",   status="pending")),
        ("approved/applied, both linkage",  dict(decision="approved",  status="applied",
                                                 ledger_posting_id=uuid.uuid4(),
                                                 disclosure_event_id=uuid.uuid4())),
        ("rejected/rejected, no linkage",   dict(decision="rejected",  status="rejected")),
        ("cancelled/cancelled, no linkage", dict(decision="cancelled", status="cancelled")),
    ]
    for label, over in legal:
        ok, ck, _ = insert_tx(**tx_kwargs(league_id, team_id, **over))
        _assert(f"S14-A {label} COMMITS", ok, f"committed={ok} constraint={ck}")

    # ══ S14-L — lifecycle-invalid rows ════════════════════════════════════
    #
    # L4-L6 are the null-decision cases. They are the proof that
    # `decision IS NOT NULL` is present: without it these three COMMIT.
    print("\nS14-L — lifecycle-invalid rows rejected by ck_faab_tx_topup_bet_lifecycle")
    lifecycle_bad = [
        ("L1 rejected/applied",        dict(decision="rejected",  status="applied")),
        ("L2 approved/rejected",       dict(decision="approved",  status="rejected")),
        ("L3 pending/failed",          dict(decision="pending",   status="failed")),
        ("L4 NULL decision/pending",   dict(decision=None,        status="pending")),
        ("L5 NULL decision/applied",   dict(decision=None,        status="applied")),
        ("L6 NULL decision/failed",    dict(decision=None,        status="failed")),
    ]
    for label, over in lifecycle_bad:
        ok, ck, _ = insert_tx(**tx_kwargs(league_id, team_id, **over))
        _assert(f"S14-{label} is REFUSED", not ok, f"committed={ok}")
        _assert(f"S14-{label} refused by {LIFECYCLE_CK}", ck == LIFECYCLE_CK, f"got {ck}")

    # ══ S14-K — linkage-invalid rows ══════════════════════════════════════
    print("\nS14-K — linkage-invalid rows rejected by ck_faab_tx_topup_bet_linkage")
    linkage_bad = [
        ("K1 approved/applied missing ledger_posting_id",
         dict(decision="approved", status="applied", disclosure_event_id=uuid.uuid4())),
        ("K2 approved/applied missing disclosure_event_id",
         dict(decision="approved", status="applied", ledger_posting_id=uuid.uuid4())),
        ("K3 approved/applied missing both",
         dict(decision="approved", status="applied")),
        ("K4 rejected/rejected carrying ledger_posting_id",
         dict(decision="rejected", status="rejected", ledger_posting_id=uuid.uuid4())),
        ("K5 rejected/rejected carrying disclosure_event_id",
         dict(decision="rejected", status="rejected", disclosure_event_id=uuid.uuid4())),
        ("K6 cancelled/cancelled carrying linkage",
         dict(decision="cancelled", status="cancelled", ledger_posting_id=uuid.uuid4())),
    ]
    for label, over in linkage_bad:
        ok, ck, _ = insert_tx(**tx_kwargs(league_id, team_id, **over))
        _assert(f"S14-{label} is REFUSED", not ok, f"committed={ok}")
        _assert(f"S14-{label} refused by {LINKAGE_CK}", ck == LINKAGE_CK, f"got {ck}")

    # ══ S14-C — legacy compatibility ══════════════════════════════════════
    #
    # 'failed' is still legal GLOBALLY, for unrelated legacy non-B6 rows, and the
    # two scoped constraints must not reach them. This is what makes the scoping
    # real rather than incidental. The legacy writer itself is never invoked.
    print("\nS14-C — a non-topup_bet row with status='failed' still commits")
    ok, ck, _ = insert_tx(
        league_id = league_id,
        team_id   = team_id,
        type      = "waiver_bid",
        amount    = 12.0,
        status    = "failed",
    )
    _assert("S14-C non-topup_bet status='failed' COMMITS (legacy compatibility kept)",
            ok, f"committed={ok} constraint={ck}")

    ok, ck, _ = insert_tx(
        league_id = league_id,
        team_id   = team_id,
        type      = "waiver_bid",
        amount    = 12.0,
        status    = "failed",
        decision  = None,
        ledger_posting_id = uuid.uuid4(),
    )
    _assert("S14-C a non-topup_bet row carrying stray linkage is OUTSIDE the scoped CHECKs",
            ok, f"committed={ok} constraint={ck}")

    # ══ C-a — disclosure uniqueness ═══════════════════════════════════════
    print("\nC-a — disclosure uniqueness (separate Group C schema scenario)")
    tdb.reset()
    league_id, team_id, req_id, app_id = seed()

    ev_a  = uuid.uuid4()
    pid_a = uuid.uuid4()
    ok, ck, tx_a = insert_tx(**tx_kwargs(
        league_id, team_id,
        decision="approved", status="applied",
        ledger_posting_id=pid_a, disclosure_event_id=ev_a,
    ))
    _assert("C-a baseline request row committed", ok, f"constraint={ck}")

    ok, ck, _ = insert_disclosure(**disclosure_kwargs(
        tx_a, league_id, team_id, req_id, app_id, event_id=ev_a))
    _assert("C-a baseline disclosure committed", ok, f"constraint={ck}")

    # duplicate event_id, different faab_transaction_id
    pid_b = uuid.uuid4()
    _, _, tx_b = insert_tx(**tx_kwargs(
        league_id, team_id,
        decision="approved", status="applied",
        ledger_posting_id=pid_b, disclosure_event_id=uuid.uuid4(),
    ))
    ok, ck, _ = insert_disclosure(**disclosure_kwargs(
        tx_b, league_id, team_id, req_id, app_id, event_id=ev_a))
    _assert("C-a duplicate event_id is REFUSED", not ok, f"committed={ok}")
    _assert(f"C-a duplicate event_id refused by {UQ_EVENT}", ck == UQ_EVENT, f"got {ck}")

    # duplicate faab_transaction_id, fresh event_id
    ok, ck, _ = insert_disclosure(**disclosure_kwargs(
        tx_a, league_id, team_id, req_id, app_id))
    _assert("C-a duplicate faab_transaction_id is REFUSED", not ok, f"committed={ok}")
    _assert(f"C-a duplicate faab_transaction_id refused by {UQ_FAAB_TX}",
            ck == UQ_FAAB_TX, f"got {ck}")

    # ══ C-b — self-approval reason ════════════════════════════════════════
    print("\nC-b — self-approval reason (separate Group C schema scenario)")
    tdb.reset()
    league_id, team_id, req_id, app_id = seed()

    def fresh_tx() -> int:
        _, _, i = insert_tx(**tx_kwargs(
            league_id, team_id,
            decision="approved", status="applied",
            ledger_posting_id=uuid.uuid4(), disclosure_event_id=uuid.uuid4(),
        ))
        return i

    bad_reasons = [
        ("NULL reason",            None),
        ("empty reason",           ""),
        ("whitespace-only reason", "   \t \n "),
    ]
    for label, reason in bad_reasons:
        ok, ck, _ = insert_disclosure(**disclosure_kwargs(
            fresh_tx(), league_id, team_id, req_id, app_id,
            self_approved=True, decision_reason=reason))
        _assert(f"C-b self_approved with {label} is REFUSED", not ok, f"committed={ok}")
        _assert(f"C-b {label} refused by {SELFAPP_CK}", ck == SELFAPP_CK, f"got {ck}")

    ok, ck, _ = insert_disclosure(**disclosure_kwargs(
        fresh_tx(), league_id, team_id, req_id, app_id,
        self_approved=True, decision_reason="Approving my own top-off; league is short."))
    _assert("C-b self_approved with a non-empty reason COMMITS", ok, f"committed={ok} constraint={ck}")

    # A NON-self-approved row needs no reason. The controlling text imposes the
    # reason requirement only on self-approval (§5.3).
    ok, ck, _ = insert_disclosure(**disclosure_kwargs(
        fresh_tx(), league_id, team_id, req_id, app_id,
        self_approved=False, decision_reason=None))
    _assert("C-b non-self-approved with NO reason COMMITS", ok, f"committed={ok} constraint={ck}")

    # ══ C-c — schema shape ════════════════════════════════════════════════
    print("\nC-c — schema shape (separate Group C schema scenario)")
    insp = inspect(tdb.engine)

    disc_cols = {c["name"] for c in insp.get_columns("top_off_disclosure")}
    expected_cols = {
        "id", "event_id", "faab_transaction_id", "league_id", "season", "team_id",
        "amount_cents", "requester_user_id", "decided_by_user_id", "self_approved",
        "decision_reason", "decided_at", "ledger_posting_id", "created_at",
    }
    _assert("C-c top_off_disclosure has exactly the §4.5 columns",
            disc_cols == expected_cols,
            f"missing={sorted(expected_cols - disc_cols)} extra={sorted(disc_cols - expected_cols)}")

    disc_uq = {u.get("name") for u in insp.get_unique_constraints("top_off_disclosure")}
    _assert(f"C-c {UQ_EVENT} exists", UQ_EVENT in disc_uq, str(sorted(disc_uq)))
    _assert(f"C-c {UQ_FAAB_TX} exists", UQ_FAAB_TX in disc_uq, str(sorted(disc_uq)))

    disc_ck = {c.get("name") for c in insp.get_check_constraints("top_off_disclosure")}
    _assert(f"C-c {SELFAPP_CK} exists", SELFAPP_CK in disc_ck, str(sorted(disc_ck)))

    faab_ck = {c.get("name") for c in insp.get_check_constraints("faab_transactions")}
    for name in (LIFECYCLE_CK, LINKAGE_CK, "ck_faab_tx_decision", "ck_faab_tx_status"):
        _assert(f"C-c {name} exists on faab_transactions", name in faab_ck, str(sorted(faab_ck)))

    faab_cols = {c["name"]: c for c in insp.get_columns("faab_transactions")}
    for name in ("requester_user_id", "decided_by_user_id", "decision", "decision_reason",
                 "decided_at", "ledger_posting_id", "disclosure_event_id",
                 "amount_cents", "season", "self_approved"):
        _assert(f"C-c faab_transactions.{name} exists", name in faab_cols,
                "column absent")
        if name in faab_cols:
            _assert(f"C-c faab_transactions.{name} is nullable",
                    faab_cols[name]["nullable"] is True,
                    f"nullable={faab_cols[name]['nullable']}")

    for name in ("ledger_posting_id", "disclosure_event_id"):
        if name in faab_cols:
            _assert(f"C-c faab_transactions.{name} is a UUID column",
                    "UUID" in str(faab_cols[name]["type"]).upper(),
                    f"type={faab_cols[name]['type']}")

    # UNIQUE-when-non-null: SQLAlchemy's unique=True renders as a unique
    # constraint or a unique index depending on backend; accept either, then
    # prove the SEMANTICS directly below rather than trusting the catalogue.
    faab_uq_names = {u.get("name") for u in insp.get_unique_constraints("faab_transactions")}
    faab_uq_cols = {tuple(u.get("column_names") or [])
                    for u in insp.get_unique_constraints("faab_transactions")}
    faab_ix_cols = {tuple(i.get("column_names") or [])
                    for i in insp.get_indexes("faab_transactions") if i.get("unique")}
    for name in ("ledger_posting_id", "disclosure_event_id"):
        _assert(f"C-c faab_transactions.{name} carries a UNIQUE constraint or index",
                (name,) in faab_uq_cols or (name,) in faab_ix_cols,
                f"uq={sorted(faab_uq_cols)} ix={sorted(faab_ix_cols)} names={sorted(faab_uq_names)}")

    # Semantics, proven not assumed: many NULLs allowed, duplicates refused.
    tdb.reset()
    league_id, team_id, req_id, app_id = seed()
    for i in range(3):
        ok, ck, _ = insert_tx(**tx_kwargs(league_id, team_id))   # both linkage NULL
        _assert(f"C-c repeated NULL linkage row {i} COMMITS (unique-when-non-null)",
                ok, f"committed={ok} constraint={ck}")

    dup_pid = uuid.uuid4()
    ok, _, _ = insert_tx(**tx_kwargs(
        league_id, team_id, decision="approved", status="applied",
        ledger_posting_id=dup_pid, disclosure_event_id=uuid.uuid4()))
    _assert("C-c first row claiming a posting id COMMITS", ok)
    ok, ck, _ = insert_tx(**tx_kwargs(
        league_id, team_id, decision="approved", status="applied",
        ledger_posting_id=dup_pid, disclosure_event_id=uuid.uuid4()))
    _assert("C-c a SECOND row claiming the same ledger_posting_id is REFUSED",
            not ok, f"committed={ok}")

    dup_ev = uuid.uuid4()
    ok, _, _ = insert_tx(**tx_kwargs(
        league_id, team_id, decision="approved", status="applied",
        ledger_posting_id=uuid.uuid4(), disclosure_event_id=dup_ev))
    _assert("C-c first row claiming a disclosure event id COMMITS", ok)
    ok, ck, _ = insert_tx(**tx_kwargs(
        league_id, team_id, decision="approved", status="applied",
        ledger_posting_id=uuid.uuid4(), disclosure_event_id=dup_ev))
    _assert("C-c a SECOND row claiming the same disclosure_event_id is REFUSED",
            not ok, f"committed={ok}")

    # §4.7 — ledger_posting_id must NOT be a foreign key: LedgerEntry.posting_id
    # is deliberately non-unique and sits on a separate declarative base.
    faab_fk_cols = {tuple(f.get("constrained_columns") or [])
                    for f in insp.get_foreign_keys("faab_transactions")}
    _assert("C-c ledger_posting_id is NOT a foreign key (§4.7)",
            ("ledger_posting_id",) not in faab_fk_cols, str(sorted(faab_fk_cols)))
    _assert("C-c disclosure_event_id is NOT a foreign key",
            ("disclosure_event_id",) not in faab_fk_cols, str(sorted(faab_fk_cols)))

    # §4.3 — the status default is now "pending".
    _assert("C-c faab_transactions.status default is 'pending'",
            str(FaabTransaction.__table__.c["status"].default.arg) == "pending",
            f"got {FaabTransaction.__table__.c['status'].default.arg!r}")


try:
    main(tdb)
finally:
    tdb.teardown()

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("All assertions PASSED")
