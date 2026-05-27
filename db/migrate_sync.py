"""
Migration: Tuesday Sync — creates tuesday_sync_runs table.
Safe to re-run: create_all is additive; existing tables are untouched.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Base, SessionLocal, engine


def run_migration() -> None:
    Base.metadata.create_all(engine)
    print("  + table ensured: tuesday_sync_runs")

    with SessionLocal() as db:
        from db.schema import TuesdaySyncRun
        n = db.query(TuesdaySyncRun).count()
        print(f"\n  Table row counts after migration:")
        print(f"    {'tuesday_sync_runs':<26} {n} rows")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: Tuesday Sync...")
    run_migration()
    print("\nDone.")
