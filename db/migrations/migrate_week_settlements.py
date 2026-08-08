#!/usr/bin/env python3
"""
migrate_week_settlements.py  —  Production schema migration for the bet
settlement run-once guard.

Creates the week_settlements table (see db/schema.py WeekSettlement model):
  One row per league per week — tracks whether settle_week() has already run
  for that week. Modeled directly on PoolPot's collection/settlement pattern
  (pool_pots table). Independent of Bet.status — this is the authoritative
  guard settle_week() checks before it will run again for a given week.

SAFE:
  - CREATE TABLE IF NOT EXISTS — safe to re-run, no-op if the table already exists.
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or does
    not point at a Postgres instance.
  - This script only creates the empty table. No backfill logic here.

USAGE:
  python db/migrations/migrate_week_settlements.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_week_settlements.py  --  week_settlements table migration\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


# ── Step 1: Create table ────────────────────────────────────────────────────

print("=" * 60)
print("STEP 1  -- Creating week_settlements table")
print("=" * 60)

try:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS week_settlements (
                id         SERIAL PRIMARY KEY,
                league_id  INTEGER REFERENCES leagues(id),
                week       INTEGER,
                settled    BOOLEAN DEFAULT FALSE,
                settled_at TIMESTAMP WITH TIME ZONE,
                UNIQUE (league_id, week)
            )
        """))
    print("\n  week_settlements table created (or already existed)")
except Exception as e:
    print(f"\n!! ERROR: CREATE TABLE failed: {e}")
    sys.exit(1)


# ── Step 2: Verify ───────────────────────────────────────────────────────────

print()
print("=" * 60)
print("STEP 2  -- Verification")
print("=" * 60)

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT to_regclass('public.week_settlements')")).scalar()
except Exception as e:
    print(f"\n!! ERROR: verification query failed: {e}")
    sys.exit(1)

print()
if result:
    print(f"  week_settlements table confirmed: {result}")
    print("  MIGRATION COMPLETE -- table exists.\n")
else:
    print("!! ERROR: week_settlements table not found after CREATE TABLE — unexpected.")
    sys.exit(1)
