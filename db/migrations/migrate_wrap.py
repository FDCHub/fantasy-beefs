"""
Migration: Weekly Wrap-Up — creates weekly_wrap_ups + wrap_up_gm_editions tables.
Safe to re-run: create_all is additive; existing tables are untouched.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from db.schema import Base, SessionLocal, engine


def run_migration() -> None:
    Base.metadata.create_all(engine)
    print("  + table ensured: weekly_wrap_ups")
    print("  + table ensured: wrap_up_gm_editions")

    with SessionLocal() as db:
        from db.schema import WeeklyWrapUp, WrapUpGmEdition
        n1 = db.query(WeeklyWrapUp).count()
        n2 = db.query(WrapUpGmEdition).count()
        print(f"\n  Table row counts after migration:")
        print(f"    {'weekly_wrap_ups':<30} {n1} rows")
        print(f"    {'wrap_up_gm_editions':<30} {n2} rows")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: Weekly Wrap-Up...")
    run_migration()
    print("\nDone.")
