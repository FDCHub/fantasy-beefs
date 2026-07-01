#!/usr/bin/env python3
"""
migrate_nfl_schedule.py  --  Create the nfl_schedule table in production.

Uses SQLAlchemy's Base.metadata.create_all(), which only creates tables that
do not already exist (equivalent to CREATE TABLE IF NOT EXISTS).  Existing
tables are never altered, dropped, or touched in any way.

No data is seeded here — schedule rows are populated by
data/ingestion/espn_schedule_connector.upsert_week_schedule().

SAFE:
  - Requires --confirm flag before any DDL executes.
  - Lists existing tables before running so you can verify nothing unexpected
    will be affected.
  - create_all() skips any table that already exists.
  - Only targets Postgres. Exits early on SQLite.

USAGE:
  python migrate_nfl_schedule.py              # dry-run: show current tables
  python migrate_nfl_schedule.py --confirm    # create nfl_schedule if missing
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIRM = "--confirm" in sys.argv

print("\nmigrate_nfl_schedule.py  --  create nfl_schedule table")
print(f"  mode : {'LIVE WRITE' if CONFIRM else 'DRY-RUN (pass --confirm to apply)'}\n")

from sqlalchemy import inspect, text
from db.schema import Base, engine, NflSchedule  # noqa: F401 — import NflSchedule so it registers with Base

db_url = str(engine.url)
if "sqlite" in db_url:
    print("!! ERROR: SQLite target detected.")
    print("   This migration targets production Postgres.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


# ── Step 1: Current tables ────────────────────────────────────────────────────

print("=" * 64)
print("STEP 1  -- Tables currently in production")
print("=" * 64)

inspector = inspect(engine)
existing  = sorted(inspector.get_table_names())
print(f"\n  {len(existing)} tables found:")
for t in existing:
    marker = "  (will be skipped)" if t != "nfl_schedule" else "  (already exists — will skip)"
    print(f"    {t}{marker if t == 'nfl_schedule' else ''}")

nfl_schedule_exists = "nfl_schedule" in existing

if nfl_schedule_exists:
    print("\n  nfl_schedule already exists — nothing to do.")
else:
    print("\n  nfl_schedule: MISSING — will be created with --confirm")

# ── Dry-run exit ──────────────────────────────────────────────────────────────

if not CONFIRM:
    print()
    print("DRY-RUN -- no DDL executed.")
    print("Re-run with --confirm to apply.\n")
    sys.exit(0)

if nfl_schedule_exists:
    print("\nNothing to do — nfl_schedule already present.\n")
    sys.exit(0)


# ── Step 2: Create missing table ──────────────────────────────────────────────

print()
print("=" * 64)
print("STEP 2  -- Running create_all() (only creates missing tables)")
print("=" * 64)

Base.metadata.create_all(engine)
print("  create_all() completed.")


# ── Step 3: Verify ────────────────────────────────────────────────────────────

print()
print("=" * 64)
print("STEP 3  -- Verification")
print("=" * 64)

inspector_after = inspect(engine)
tables_after    = sorted(inspector_after.get_table_names())
new_tables      = sorted(set(tables_after) - set(existing))

print(f"\n  Tables before : {len(existing)}")
print(f"  Tables after  : {len(tables_after)}")
print(f"  New tables    : {new_tables}")

ok_created     = "nfl_schedule" in tables_after
ok_no_surprise = all(t == "nfl_schedule" for t in new_tables)

print(f"\n  nfl_schedule created       : {'OK' if ok_created     else 'FAIL'}")
print(f"  No unexpected tables added : {'OK' if ok_no_surprise else 'WARN -- unexpected: ' + str([t for t in new_tables if t != 'nfl_schedule'])}")

# Spot-check columns
if ok_created:
    cols = {c["name"] for c in inspector_after.get_columns("nfl_schedule")}
    expected = {"id", "season", "week", "home_team", "away_team", "kickoff_utc", "last_synced_at"}
    missing_cols = expected - cols
    print(f"  Expected columns present   : {'OK' if not missing_cols else 'FAIL -- missing: ' + str(missing_cols)}")

print()
if ok_created:
    print("  MIGRATION COMPLETE -- nfl_schedule table created.")
else:
    print("  !! MIGRATION FAILED -- nfl_schedule not found after create_all().")
    sys.exit(1)

print()
