"""Migration — add team_id column to beef_starters.

Safe to re-run: skips the ALTER TABLE if the column already exists.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import inspect, text
from db.schema import engine


def run_migration() -> None:
    with engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM beef_starters")).scalar()
        print(f"[migrate_beef_starters_team_id] beef_starters rows before: {before}")

        insp = inspect(engine)
        existing_cols = {c["name"] for c in insp.get_columns("beef_starters")}

        if "team_id" in existing_cols:
            print("[migrate_beef_starters_team_id] team_id column already exists — skipping ALTER TABLE")
        else:
            # PostgreSQL and SQLite both accept this syntax.
            # Existing rows get NULL; the column is NOT NULL in the ORM model
            # but the DB-level constraint is added here only if the table is empty
            # (prod table has 0 rows from the first migration).
            conn.execute(text("ALTER TABLE beef_starters ADD COLUMN team_id INTEGER"))
            conn.commit()
            print("[migrate_beef_starters_team_id] team_id column added")

        after = conn.execute(text("SELECT COUNT(*) FROM beef_starters")).scalar()
        print(f"[migrate_beef_starters_team_id] beef_starters rows after:  {after}")


if __name__ == "__main__":
    run_migration()
