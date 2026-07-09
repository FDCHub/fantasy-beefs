"""
Migration: league economy stop — adds economy_stop_weekly_min_cents to
leagues, so the Discrete-Stop Economy Table's selection lives on League
itself, independent of LeagueTreasury (B1-12).

Safe to re-run:
  • ALTER TABLE ADD COLUMN is wrapped in a try/except for idempotency.
  • The new column is nullable with no default — an unconfigured league
    (NULL) falls back to the default stop at read time (see
    payments/economy_config.py's get_league_economy_stop()), so existing
    rows don't need a backfilled value.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from db.schema import SessionLocal, engine


_ALTER_LEAGUES = [
    "ALTER TABLE leagues ADD COLUMN economy_stop_weekly_min_cents INTEGER",
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
            _ = league.economy_stop_weekly_min_cents
            print(f"\n  leagues.economy_stop_weekly_min_cents verified on league #{league.id}")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: league_economy_stop...")
    run_migration()
    print("\nDone.")
