#!/usr/bin/env python3
"""
seed_roster_slots.py  —  Backfill Roster.slot from Yahoo selected_position data.

STATUS: INCOMPLETE — stopped at Step 3 (schema audit) pending design decision.
See output / README below for the architectural issue that must be resolved first.

Steps when complete:
  1. Load Yahoo OAuth tokens from secrets/private.json + yahoo_oauth.json
  2. Load DB team list (team_id → yahoo_team_id)
  3. *** STOP *** — Roster table has no week dimension (see audit below)
  4. (pending) Fetch selected_position for each player from Yahoo roster API
  5. (pending) Write slot values back to Roster rows
  6. (pending) Verify: print before/after slot distributions

USAGE:
  python seed_roster_slots.py              # audit only — no writes, no API calls
  python seed_roster_slots.py --confirm    # (blocked — see step 3)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIRM = "--confirm" in sys.argv

print("\nseed_roster_slots.py  --  Roster.slot backfill (Yahoo selected_position)")
print(f"  mode : {'LIVE WRITE (blocked -- see Step 3)' if CONFIRM else 'AUDIT ONLY'}\n")

from sqlalchemy import text
from db.schema import engine, SessionLocal


# ── Step 1: Confirm slot column exists in target DB ───────────────────────────

print("=" * 60)
print("STEP 1  -- Confirm rosters.slot exists in target DB")
print("=" * 60)

with engine.connect() as conn:
    slot_exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE  table_name  = 'rosters'
        AND    column_name = 'slot'
    """)).scalar()

if not slot_exists:
    print("\n!! BLOCKED: rosters.slot column does not exist in this DB.")
    print("   Run migrate_lineup_schema.py --confirm first, then re-run this script.")
    sys.exit(1)

print(f"\n  rosters.slot column : EXISTS -- OK\n")


# ── Step 2: Count Roster rows and current slot coverage ───────────────────────

print("=" * 60)
print("STEP 2  -- Current Roster state")
print("=" * 60)

with engine.connect() as conn:
    total_roster = conn.execute(
        text("SELECT COUNT(*) FROM rosters")
    ).scalar()

    slot_null = conn.execute(
        text("SELECT COUNT(*) FROM rosters WHERE slot IS NULL")
    ).scalar()

    slot_set = conn.execute(
        text("SELECT COUNT(*) FROM rosters WHERE slot IS NOT NULL")
    ).scalar()

    slot_dist = conn.execute(text("""
        SELECT slot, COUNT(*) AS n
        FROM   rosters
        WHERE  slot IS NOT NULL
        GROUP  BY slot
        ORDER  BY n DESC
    """)).fetchall()

    unique_constraint = conn.execute(text("""
        SELECT conname, pg_get_constraintdef(oid)
        FROM   pg_constraint
        WHERE  conrelid = 'rosters'::regclass
        AND    contype  IN ('u','p')
        ORDER  BY conname
    """)).fetchall()

    columns = conn.execute(text("""
        SELECT column_name, is_nullable, data_type
        FROM   information_schema.columns
        WHERE  table_name = 'rosters'
        ORDER  BY ordinal_position
    """)).fetchall()

print(f"\n  Total Roster rows   : {total_roster}")
print(f"  slot IS NULL        : {slot_null}")
print(f"  slot IS NOT NULL    : {slot_set}")

if slot_dist:
    print(f"\n  Current slot distribution:")
    for slot, n in slot_dist:
        print(f"    {slot:<8} {n}")

print(f"\n  Roster columns:")
for col, nullable, dtype in columns:
    print(f"    {col:<20} {dtype:<15} nullable={nullable}")

print(f"\n  Roster unique/primary constraints:")
for name, defn in unique_constraint:
    print(f"    {name:<30} {defn}")


# ── Step 3: CRITICAL SCHEMA AUDIT — STOP ──────────────────────────────────────

print()
print("=" * 60)
print("STEP 3  -- CRITICAL SCHEMA AUDIT  ***  STOP  ***")
print("=" * 60)
print("""
  FINDING: The rosters table has NO week dimension.

  Current schema:
    UniqueConstraint("team_id", "player_id")   <-- one row per team+player
    slot VARCHAR NULL                           <-- single value per team+player

  The problem:
    A player's lineup slot changes week to week. A WR might start in
    the FLEX slot week 1, get injured and go to BN week 2, come back
    as WR1 week 6. There is no way to store 17 weeks of slot history
    in the current Roster table:

      OPTION A: Overwrite slot on each weekly run (last-write wins)
        - Fast. Simple. Loses all history.
        - settle_the_lineup() for PAST weeks would use the CURRENT slot,
          not the slot the player was actually in that week.
        - Only correct for the CURRENT week's bet settlement.
        - Settlement for any closed week would be WRONG.

      OPTION B: Add a week column to Roster (roster becomes weekly)
        - UniqueConstraint becomes ("team_id", "player_id", "week")
        - One row per team+player+week (12 teams x 15 players x 17 weeks = 3,060 rows)
        - settle_the_lineup() queries Roster WHERE week = bet.week — correct always.
        - Requires ALTER TABLE rosters ADD COLUMN week INT NULL (nullable for
          pre-migration rows), then seed 17 weeks of slot data.
        - More complex to backfill: 17 Yahoo API calls per team (204 total).

      OPTION C: Store slot data in a separate RosterSlot table
        - Leave Roster as-is (team-level). Add: RosterSlot(team_id, player_id,
          week, slot) with its own unique constraint.
        - settle_the_lineup() queries RosterSlot, falls back to Roster.slot
          if no weekly row exists.
        - Most flexible, but adds a second table and a join.

  What settle_the_lineup() CURRENTLY does (settlement_engine.py):
    - Queries Roster filtered on slot NOT IN ('BN','IR')
    - Null-slot rows are INCLUDED (backward compat for pre-migration rows)
    - Uses slot column directly — NO week filter on Roster
    - This means without a week dimension, the starter list for ANY week
      would be based on the most-recently-written slot — which may be wrong
      for any week except the most recent.

  RECOMMENDATION:
    Option B (add week column to Roster) is the cleanest fix.
    It keeps the data in one table, makes the settlement query trivially
    correct, and the backfill is 204 API calls (already patterned from
    seed_yahoo_projections.py).

    If Option A (overwrite-only) is acceptable, this script can proceed
    immediately — but you must acknowledge that past-week The Lineup
    settlement will use wrong slot data for settled bets.

  THIS SCRIPT IS STOPPED. No API calls. No DB writes.

  Report back which option to use before proceeding:
    A) Overwrite slot (current week only — past weeks wrong)
    B) Add week column to Roster (correct for all weeks — schema change needed)
    C) Separate RosterSlot table (most flexible — new table needed)
""")

if CONFIRM:
    print("  --confirm flag was passed but THIS SCRIPT WILL NOT WRITE ANYTHING.")
    print("  Resolve the schema question above first.\n")

sys.exit(0)
