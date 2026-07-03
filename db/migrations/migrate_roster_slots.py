#!/usr/bin/env python3
"""
migrate_roster_slots.py  —  Production schema migration for weekly roster history.

Creates the roster_slots table (see db/schema.py RosterSlot model):
  One row per team, player, and week. Insert-only — never overwritten.
  Read by weekly_wrap.py and bet settlement to answer "what was true that week."

SAFE:
  - CREATE TABLE IF NOT EXISTS — safe to re-run, no-op if the table already exists.
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or does
    not point at a Postgres instance.
  - This script only creates the empty table. No backfill logic here.

USAGE:
  python db/migrations/migrate_roster_slots.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_roster_slots.py  --  roster_slots table migration\n")

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
print("STEP 1  -- Creating roster_slots table")
print("=" * 60)

try:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS roster_slots (
                id         SERIAL PRIMARY KEY,
                league_id  INTEGER NOT NULL REFERENCES leagues(id),
                team_id    INTEGER NOT NULL REFERENCES teams(id),
                player_id  INTEGER NOT NULL REFERENCES players(id),
                week       INTEGER NOT NULL,
                slot       VARCHAR NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                UNIQUE (team_id, player_id, week)
            )
        """))
    print("\n  roster_slots table created (or already existed)")
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
        result = conn.execute(text("SELECT to_regclass('public.roster_slots')")).scalar()
except Exception as e:
    print(f"\n!! ERROR: verification query failed: {e}")
    sys.exit(1)

print()
if result:
    print(f"  roster_slots table confirmed: {result}")
    print("  MIGRATION COMPLETE -- table exists.\n")
else:
    print("!! ERROR: roster_slots table not found after CREATE TABLE — unexpected.")
    sys.exit(1)
