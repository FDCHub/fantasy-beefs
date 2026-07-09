"""
Migration: economy config — adds the B1 Discrete-Stop Economy Table
snapshot columns (buyin_cents, wallet_cents, reserve_cents) to
buy_in_records.

Safe to re-run:
  • ALTER TABLE ADD COLUMN is wrapped in a try/except for idempotency.
  • Each new column gets DEFAULT 0 so the ALTER succeeds against any
    existing rows (NOT NULL with no default fails on a non-empty table).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from db.schema import SessionLocal, engine


_ALTER_BUYIN_RECORDS = [
    "ALTER TABLE buy_in_records ADD COLUMN buyin_cents   INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE buy_in_records ADD COLUMN wallet_cents  INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE buy_in_records ADD COLUMN reserve_cents INTEGER NOT NULL DEFAULT 0",
]


def run_migration() -> None:
    # ── New columns on existing buy_in_records table ─────────────────────────
    with engine.connect() as conn:
        for stmt in _ALTER_BUYIN_RECORDS:
            col = stmt.split("ADD COLUMN")[1].strip().split()[0]
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"  + buy_in_records.{col} added")
            except Exception:
                print(f"  . buy_in_records.{col} already exists — skipped")

    # ── Verify ────────────────────────────────────────────────────────────────
    with SessionLocal() as db:
        from db.schema import BuyInRecord
        print()
        n = db.query(BuyInRecord).count()
        print(f"  Table row counts after migration:")
        print(f"    {BuyInRecord.__tablename__:<22} {n} rows")

        record = db.query(BuyInRecord).first()
        if record:
            _ = record.buyin_cents, record.wallet_cents, record.reserve_cents
            print(f"\n  buy_in_records.buyin_cents / wallet_cents / reserve_cents "
                  f"verified on record #{record.id}")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: economy_config...")
    run_migration()
    print("\nDone.")
