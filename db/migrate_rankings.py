"""
Migration v9 — power_rankings table.

Safe to re-run: create_all() is additive.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Base, SessionLocal, engine


def run_migration() -> None:
    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        from sqlalchemy import text
        row = db.execute(text("SELECT COUNT(*) FROM power_rankings")).scalar()
        print(f"[migrate_rankings] power_rankings table ready — {row} existing row(s)")


if __name__ == "__main__":
    run_migration()
