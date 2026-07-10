"""
Migration: buyin enforcement — adds League.buyin_enforcement_active
(B2, Finding 5.3). Explicit, commissioner-set activation for the buy-in
gate, independent of LeagueTreasury.

Safe to re-run:
  • ALTER TABLE ADD COLUMN is wrapped in a try/except for idempotency.
  • DEFAULT 0 (false) matches the real current behavior of every league
    in production today — this migration changes nothing for existing
    leagues the instant it deploys.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from db.schema import SessionLocal, engine


_ALTER_LEAGUES = [
    "ALTER TABLE leagues ADD COLUMN buyin_enforcement_active BOOLEAN NOT NULL DEFAULT 0",
]


def run_migration() -> None:
    # ── New column on existing leagues table ─────────────────────────────────
    with engine.connect() as conn:
        for stmt in _ALTER_LEAGUES:
            col = stmt.split("ADD COLUMN")[1].strip().split()[0]
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"  + leagues.{col} added")
            except Exception:
                print(f"  . leagues.{col} already exists — skipped")

    # ── Verify ────────────────────────────────────────────────────────────────
    with SessionLocal() as db:
        from db.schema import League
        print()
        n = db.query(League).count()
        print(f"  Table row counts after migration:")
        print(f"    {League.__tablename__:<22} {n} rows")

        league = db.query(League).first()
        if league:
            _ = league.buyin_enforcement_active
            print(f"\n  leagues.buyin_enforcement_active verified on league #{league.id} "
                  f"(value={league.buyin_enforcement_active})")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: buyin_enforcement...")
    run_migration()
    print("\nDone.")
