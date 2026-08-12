"""P1-L2 — the legacy confirm_topup credit path is RETIRED, at two levels.

WHAT THIS SUITE WAS, AND WHY IT CHANGED (WP5).

It began as a RED spec against 77fd23c. `deposit()` self-committed and
`confirm_topup()` committed again, so the passed session saw TWO commit
boundaries and a wallet credit could persist without the audit row and the
status change that belonged with it. The target was "confirm_topup owns exactly
one commit boundary", and the suite exited 1 on purpose while that stood.

THE BOUNDARY WAS NOT REPAIRED IN PLACE — THE WRITER WAS RETIRED. B6 §11.5
replaced it: `confirm_topup()` now raises `TopUpsUnavailableError` as its FIRST
executable statement, and the replacement — `approve_top_off()` behind
`POST /league/{id}/top-offs/{id}/approve` — posts two balanced legs, mirrors the
Wallet from the ledger's own post-state, writes the disclosure and commits ONCE,
under three row locks. That is the sole-commit property the RED target wanted,
achieved by a writer that also fixes what the original could not.

THE FIXTURE ITSELF STOPPED BEING CONSTRUCTIBLE, which is why this suite crashed
rather than failed: it seeded a pending `topup_bet` FaabTransaction with a NULL
decision, and `ck_faab_tx_topup_bet_lifecycle` now refuses that row outright. An
IntegrityError during setup reads like a broken test; it was the schema doing
its job.

SO THE PROPERTY IS ASSERTED WHERE IT NOW LIVES, at both levels the retirement
uses — the writer refuses, and the row shape it depended on is unrepresentable.

REPLACEMENT COVERAGE for the governed writer:
    test_b6_group_e_issuance_pg.py      balanced issuance, one commit, locked
    test_b6_group_d_authority_lock_pg.py  the locks that make it safe
    test_b6_group_c_provenance_disclosure_pg.py  the disclosure it writes
"""
import os, sys, tempfile

os.environ.pop("STRIPE_SECRET_KEY", None)
_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'p1l2_solecommit.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.exc import IntegrityError

from db.schema import (Base, engine, SessionLocal, League, Team, Wallet,
                       FaabWallet, FaabTransaction, Transaction)
from ledger.ledger import create_ledger_table, trial_balance
from wallet.faab_wallet import TopUpsUnavailableError, confirm_topup

Base.metadata.create_all(engine)
create_ledger_table()
_failures: list[str] = []


def _assert(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not condition:
        _failures.append(label)


def _make_team():
    with SessionLocal() as db:
        lg = League(season=2025, name="P1L2 sole", projection_source="fantasypros")
        db.add(lg); db.flush()
        t = Team(league_id=lg.id, team_name="P1L2 sole", owner="R1", email="r1@p1l2.com")
        db.add(t); db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(FaabWallet(team_id=t.id, league_id=lg.id, waiver_balance=0.0))
        db.commit()
        return lg.id, t.id


print("=" * 60)
print("P1-L2 — legacy confirm_topup credit path is retired")
print("=" * 60)

league_id, tid = _make_team()

# ── Level 1 · the ROW SHAPE the legacy lifecycle needed is unrepresentable ────
#
# This is what the old fixture tried to seed. `ck_faab_tx_topup_bet_lifecycle`
# requires a topup_bet row to carry a decision paired with its status, so a
# pending row with a NULL decision — exactly what legacy creation produced —
# cannot exist. The legacy lifecycle is therefore not merely unreachable; it is
# unrepresentable, which is the stronger of the two.
refused = False
with SessionLocal() as db:
    db.add(FaabTransaction(
        league_id=league_id, team_id=tid, type="topup_bet", amount=25.00,
        wallet_from="stripe", wallet_to="bet", status="pending",
        note="the legacy pending row the RED fixture used to seed"))
    try:
        db.flush()
    except IntegrityError:
        refused = True
        db.rollback()

_assert("SCHEMA: a legacy pending topup_bet row with no decision is refused",
        refused,
        "ck_faab_tx_topup_bet_lifecycle — the legacy lifecycle is "
        "unrepresentable, not merely unreachable")

# ── Level 2 · the WRITER refuses before it can move anything ──────────────────

with SessionLocal() as db:
    rows_before = db.query(FaabTransaction).count()
    wallet_before = db.query(Wallet).filter(Wallet.team_id == tid).first().balance
    tx_before = db.query(Transaction).count()
tb_before = trial_balance()

raised = None
with SessionLocal() as db:
    try:
        # The id is deliberately one that does not exist: B6 §11.5 requires the
        # refusal to be the FIRST executable statement, BEFORE the lookup. A
        # writer that raised "not found" instead would have done a database read
        # on a retired path, and a later edit could have moved money behind it.
        confirm_topup(999_999, db)
    except TopUpsUnavailableError as exc:
        raised = exc

_assert("WRITER: confirm_topup refuses rather than crediting",
        raised is not None, "expected TopUpsUnavailableError")
_assert("WRITER: it refuses BEFORE looking the row up — not 'not found'",
        raised is not None and "not found" not in str(raised).lower(),
        str(raised)[:120] if raised else "no exception raised")
_assert("WRITER: and it names the governed replacement",
        raised is not None and "top-offs" in str(raised).lower(),
        str(raised)[:120] if raised else "no exception raised")

with SessionLocal() as db:
    rows_after = db.query(FaabTransaction).count()
    wallet_after = db.query(Wallet).filter(Wallet.team_id == tid).first().balance
    tx_after = db.query(Transaction).count()

# THE ORIGINAL RED TARGET'S SUBSTANCE: no partial credit can persist. The old
# suite proved it by counting commit boundaries; there is now no boundary to
# count, because nothing is written at all.
_assert("NO CREDIT: the wallet balance is unchanged",
        wallet_after == wallet_before, f"{wallet_before} -> {wallet_after}")
_assert("NO CREDIT: no deposit audit row was written",
        tx_after == tx_before == 0, f"{tx_before} -> {tx_after}")
_assert("NO CREDIT: no FaabTransaction row was written",
        rows_after == rows_before == 0, f"{rows_before} -> {rows_after}")
_assert("NO CREDIT: the ledger is untouched and still balances",
        trial_balance() == tb_before == 0, f"{tb_before} -> {trial_balance()}")

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("P1-L2 CONFIRM-TOPUP RETIREMENT — all assertions PASSED")