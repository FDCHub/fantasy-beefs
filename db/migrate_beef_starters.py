"""Migration — create beef_starters table.

Uses BeefStarter.__table__.create(checkfirst=True) so it is safe to
re-run: a no-op if the table already exists.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import BeefStarter, engine


def run_migration() -> None:
    BeefStarter.__table__.create(engine, checkfirst=True)
    with engine.connect() as conn:
        from sqlalchemy import text
        count = conn.execute(text("SELECT COUNT(*) FROM beef_starters")).scalar()
    print(f"[migrate_beef_starters] beef_starters table ready — {count} existing row(s)")


if __name__ == "__main__":
    run_migration()
