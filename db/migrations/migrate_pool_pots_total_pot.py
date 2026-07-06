#!/usr/bin/env python3
"""
migrate_pool_pots_total_pot.py  —  Production schema migration for the Batch C
pool-settlement fix.

Adds the total_pot column (see db/schema.py PoolPot model):
  Nullable, no default. Persists the real dollar total collected for a
  week's pool (weekly_entry * charged, where charged is the count of teams
  actually debited) so settle_pool() reads this frozen figure instead of
  recomputing weekly_entry * num_teams — the recompute paid out for every
  team in the league, including any that never had a wallet to be debited
  from at collection.

  NULL on all existing rows by design — no backfill. Those weeks are
  already settled and never re-read; settle_pool()'s NULL guard only fires
  for a week where collection never ran (or predates this fix), which is
  the correct error state.

SAFE:
  - ADD COLUMN IF NOT EXISTS — safe to re-run, no-op if the column already exists.
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or does
    not point at a Postgres instance.
  - No backfill — this script only adds the empty column.

USAGE:
  python db/migrations/migrate_pool_pots_total_pot.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_pool_pots_total_pot.py  --  pool_pots.total_pot column migration\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


# ── Step 1: Add column ────────────────────────────────────────────────────────

print("=" * 60)
print("STEP 1  -- Adding pool_pots.total_pot column")
print("=" * 60)

try:
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE pool_pots ADD COLUMN IF NOT EXISTS total_pot DOUBLE PRECISION"
        ))
    print("\n  pool_pots.total_pot column added (or already existed)")
except Exception as e:
    print(f"\n!! ERROR: ALTER TABLE failed: {e}")
    sys.exit(1)


# ── Step 2: Verify ───────────────────────────────────────────────────────────

print()
print("=" * 60)
print("STEP 2  -- Verification")
print("=" * 60)

try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'pool_pots' AND column_name = 'total_pot'
        """)).scalar()
except Exception as e:
    print(f"\n!! ERROR: verification query failed: {e}")
    sys.exit(1)

print()
if result:
    print(f"  pool_pots.total_pot column confirmed: {result}")
    print("  MIGRATION COMPLETE -- column exists.\n")
else:
    print("!! ERROR: pool_pots.total_pot column not found after ALTER TABLE — unexpected.")
    sys.exit(1)
