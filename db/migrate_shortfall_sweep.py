"""
Migration: shortfall sweep — creates shortfall_sweep_records (B2, Section 6).
One row per team per week; idempotency guard + reporting metadata for the
weekly shortfall-to-championship sweep. The ledger's own entries remain
the source of truth for money movement — this table never holds money.

Safe to re-run: create_all is additive for new tables.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Base, SessionLocal, engine


_NEW_TABLES = ["shortfall_sweep_records"]


def run_migration() -> None:
    Base.metadata.create_all(engine)
    print(f"  + tables ensured: {', '.join(_NEW_TABLES)}")

    with SessionLocal() as db:
        from db.schema import ShortfallSweepRecord
        print()
        print("  Table row counts after migration:")
        n = db.query(ShortfallSweepRecord).count()
        print(f"    {ShortfallSweepRecord.__tablename__:<26} {n} rows")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: shortfall_sweep...")
    run_migration()
    print("\nDone.")
