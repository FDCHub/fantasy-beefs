"""
test_buyin_ledger.py — Session B1: create_buyin_link() / confirm_buyin_payment()
posting through the ledger via the Discrete-Stop Economy Table.

No prior test coverage existed for payments/stripe_connect.py at all
(confirmed via recon) — these are the only tests for this file.

Covers:
  1. create_buyin_link() charges the configured stop's buyin_cents and
     snapshots all three values onto the new BuyInRecord columns —
     for EVERY one of the five stops, not just the default.
  2. confirm_buyin_payment() posts a real Door 1 ledger entry; after
     confirmation, balance_of(wallet:*) and balance_of(reserve:*) equal
     the record's stored wallet_cents/reserve_cents exactly — for every
     stop.
  3. A forced LedgerImbalanceError (corrupting one of the three stored
     columns) leaves record.status unchanged and posts nothing at all
     (full rollback).
  4. Idempotency — calling confirm_buyin_payment() twice on an
     already-paid record does not double-post.

Runs entirely in MOCK_MODE (no STRIPE_SECRET_KEY set), so no real
Stripe calls are made. Uses a temp SQLite DB so prod is never touched.
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_buyin_ledger.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.pop("STRIPE_SECRET_KEY", None)  # force MOCK_MODE regardless of shell env

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import Base, engine, SessionLocal, BuyInRecord, League, LeagueTreasury, Team
from payments.economy_config import ECONOMY_STOPS
from payments.stripe_connect import (
    setup_league_treasury,
    create_buyin_link,
    confirm_buyin_payment,
    MOCK_MODE,
)
from ledger.ledger import balance_of, trial_balance, create_ledger_table, LedgerImbalanceError

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── DB bootstrap ──────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)
create_ledger_table()
_assert("running in MOCK_MODE (no real Stripe calls)", MOCK_MODE is True)


def _make_league_and_team(name: str) -> tuple[int, int]:
    with SessionLocal() as db:
        league = League(season=2025, name=f"B1 Test League {name}", projection_source="fantasypros")
        db.add(league)
        db.flush()
        team = Team(league_id=league.id, team_name=f"Team {name}", owner=f"Owner {name}", email=f"{name}@t.com")
        db.add(team)
        db.commit()
        return league.id, team.id


# ── SCENARIO 1: every one of the five stops — link creation snapshots correctly,
# confirmation posts correctly through the ledger ──────────────────────────────

print("\nScenario 1: create_buyin_link() + confirm_buyin_payment() across all five stops")

for i, stop in enumerate(ECONOMY_STOPS):
    league_id, team_id = _make_league_and_team(f"stop{i}")

    with SessionLocal() as db:
        setup_league_treasury(league_id, stop.buyin_cents, db)

    with SessionLocal() as db:
        link = create_buyin_link(league_id, team_id, db)

    with SessionLocal() as db:
        record = db.query(BuyInRecord).filter(BuyInRecord.id == link.record_id).first()
        _assert(f"stop {stop.weekly_min_cents}: amount_cents == stop.buyin_cents", record.amount_cents == stop.buyin_cents, f"got {record.amount_cents}")
        _assert(f"stop {stop.weekly_min_cents}: buyin_cents snapshot correct", record.buyin_cents == stop.buyin_cents, f"got {record.buyin_cents}")
        _assert(f"stop {stop.weekly_min_cents}: wallet_cents snapshot correct", record.wallet_cents == stop.wallet_cents, f"got {record.wallet_cents}")
        _assert(f"stop {stop.weekly_min_cents}: reserve_cents snapshot correct", record.reserve_cents == stop.reserve_cents, f"got {record.reserve_cents}")
        _assert(f"stop {stop.weekly_min_cents}: record status is pending before confirmation", record.status == "pending")

    with SessionLocal() as db:
        confirmed = confirm_buyin_payment(link.record_id, db)
    _assert(f"stop {stop.weekly_min_cents}: status flipped to paid", confirmed.status == "paid")

    _assert(
        f"stop {stop.weekly_min_cents}: balance_of(wallet:{team_id}) == record.wallet_cents",
        balance_of(f"wallet:{team_id}") == stop.wallet_cents,
        f"got {balance_of(f'wallet:{team_id}')}, want {stop.wallet_cents}",
    )
    _assert(
        f"stop {stop.weekly_min_cents}: balance_of(reserve:{team_id}) == record.reserve_cents",
        balance_of(f"reserve:{team_id}") == stop.reserve_cents,
        f"got {balance_of(f'reserve:{team_id}')}, want {stop.reserve_cents}",
    )
    _assert(f"stop {stop.weekly_min_cents}: trial_balance still closes to 0", trial_balance() == 0, f"got {trial_balance()}")


# ── SCENARIO 2: forced LedgerImbalanceError — full rollback ───────────────────
# Corrupt wallet_cents on a fresh, unpaid record so wallet_cents + reserve_cents
# != buyin_cents — post() must reject the whole posting, and record.status
# must stay "pending", not "paid".

print("\nScenario 2: forced LedgerImbalanceError — record.status unchanged, no partial ledger entries")

league_id2, team_id2 = _make_league_and_team("imbalance")
default_stop = ECONOMY_STOPS[1]
with SessionLocal() as db:
    setup_league_treasury(league_id2, default_stop.buyin_cents, db)
with SessionLocal() as db:
    link2 = create_buyin_link(league_id2, team_id2, db)

# Corrupt the snapshot directly in the fixture — simulates a stored-column
# corruption, independent of create_buyin_link's own (correct) behavior.
with SessionLocal() as db:
    record2 = db.query(BuyInRecord).filter(BuyInRecord.id == link2.record_id).first()
    record2.wallet_cents += 1  # now wallet_cents + reserve_cents != buyin_cents
    db.commit()

tb_before_imbalance = trial_balance()
raised_imbalance = False
try:
    with SessionLocal() as db:
        confirm_buyin_payment(link2.record_id, db)
except LedgerImbalanceError:
    raised_imbalance = True
_assert("LedgerImbalanceError raised for the corrupted snapshot", raised_imbalance)

with SessionLocal() as db:
    record2_after = db.query(BuyInRecord).filter(BuyInRecord.id == link2.record_id).first()
_assert("record.status is still 'pending', NOT 'paid'", record2_after.status == "pending", f"got {record2_after.status}")
_assert("record.paid_at is still unset", record2_after.paid_at is None)
_assert("wallet:<team2> ledger balance is 0 — no partial posting", balance_of(f"wallet:{team_id2}") == 0, f"got {balance_of(f'wallet:{team_id2}')}")
_assert("reserve:<team2> ledger balance is 0 — no partial posting", balance_of(f"reserve:{team_id2}") == 0, f"got {balance_of(f'reserve:{team_id2}')}")
_assert("trial_balance unchanged after the rejected posting", trial_balance() == tb_before_imbalance, f"before={tb_before_imbalance} after={trial_balance()}")


# ── SCENARIO 3: idempotency — confirming twice does not double-post ──────────

print("\nScenario 3: idempotency — confirm_buyin_payment() called twice does not double-post")

league_id3, team_id3 = _make_league_and_team("idempotent")
with SessionLocal() as db:
    setup_league_treasury(league_id3, default_stop.buyin_cents, db)
with SessionLocal() as db:
    link3 = create_buyin_link(league_id3, team_id3, db)

with SessionLocal() as db:
    confirm_buyin_payment(link3.record_id, db)
with SessionLocal() as db:
    confirm_buyin_payment(link3.record_id, db)  # second call — must be a no-op

_assert(
    "wallet:<team3> ledger balance reflects exactly ONE posting, not two",
    balance_of(f"wallet:{team_id3}") == default_stop.wallet_cents,
    f"got {balance_of(f'wallet:{team_id3}')}, want {default_stop.wallet_cents} (not {default_stop.wallet_cents * 2})",
)
_assert(
    "reserve:<team3> ledger balance reflects exactly ONE posting, not two",
    balance_of(f"reserve:{team_id3}") == default_stop.reserve_cents,
    f"got {balance_of(f'reserve:{team_id3}')}, want {default_stop.reserve_cents}",
)
_assert("trial_balance still closes to 0 after the idempotency check", trial_balance() == 0, f"got {trial_balance()}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
