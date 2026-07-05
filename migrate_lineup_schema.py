#!/usr/bin/env python3
"""
migrate_lineup_schema.py  —  Production schema migration for The Lineup feature.

Applies three changes that exist in db/schema.py but NOT yet in production Postgres:
  1. ALTER TABLE bets: drop ck_bet_status, re-add with 'push' included
  2. ALTER TABLE bets: drop ck_bet_type, re-add with 'the_lineup' included
  3. ALTER TABLE rosters: ADD COLUMN slot VARCHAR NULL  (idempotent — skips if exists)

SAFE:
  - Requires --confirm flag before any DDL executes.
  - Prints current constraint definitions before altering so you can verify.
  - Each step is idempotent: dropping a non-existent constraint is caught and
    reported as a warning, not an error.
  - Only targets Postgres. Exits early on SQLite.

USAGE:
  python migrate_lineup_schema.py              # dry-run: print plan, no DDL
  python migrate_lineup_schema.py --confirm    # live write to DATABASE_URL
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIRM = "--confirm" in sys.argv

print("\nmigrate_lineup_schema.py  --  The Lineup production schema migration")
print(f"  mode : {'LIVE WRITE' if CONFIRM else 'DRY-RUN (pass --confirm to apply)'}\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if "sqlite" in db_url:
    print("!! ERROR: SQLite target detected.")
    print("   This migration uses Postgres DDL (DROP CONSTRAINT, ADD COLUMN IF NOT EXISTS).")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


# ── Step 1: Print current constraint definitions ───────────────────────────────

print("=" * 60)
print("STEP 1  -- Current constraint definitions in production")
print("=" * 60)

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT conname, pg_get_constraintdef(oid) AS definition
        FROM   pg_constraint
        WHERE  conrelid = 'bets'::regclass
        AND    contype  = 'c'
        ORDER  BY conname
    """)).fetchall()

    if rows:
        for name, defn in rows:
            marker = " <-- WILL ALTER" if name in ("ck_bet_status", "ck_bet_type") else ""
            print(f"  {name:<25} {defn}{marker}")
    else:
        print("  (no check constraints found on bets — unexpected)")

    slot_exists = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE  table_name  = 'rosters'
        AND    column_name = 'slot'
    """)).scalar()

    print()
    print(f"  rosters.slot column : {'EXISTS (will skip ADD COLUMN)' if slot_exists else 'MISSING (will ADD COLUMN)'}")


# ── Dry-run exit ───────────────────────────────────────────────────────────────

if not CONFIRM:
    print()
    print("DRY-RUN -- no DDL executed.")
    print("Re-run with --confirm to apply.\n")
    sys.exit(0)


# ── Step 2: Apply migrations ───────────────────────────────────────────────────

print()
print("=" * 60)
print("STEP 2  -- Applying migrations")
print("=" * 60)

with engine.begin() as conn:

    # --- 2a. ck_bet_status: drop old, add new with 'push' ----------------------

    print("\n  2a. ck_bet_status ...")
    try:
        conn.execute(text("ALTER TABLE bets DROP CONSTRAINT ck_bet_status"))
        print("      dropped old ck_bet_status")
    except Exception as e:
        print(f"      WARNING: could not drop ck_bet_status: {e}")
        print("      (may not exist — continuing)")

    conn.execute(text(
        "ALTER TABLE bets ADD CONSTRAINT ck_bet_status "
        "CHECK (status IN ('pending','won','lost','push'))"
    ))
    print("      added ck_bet_status with 'push'")

    # --- 2b. ck_bet_type: drop old, add new with 'the_lineup' -----------------

    print("\n  2b. ck_bet_type ...")
    try:
        conn.execute(text("ALTER TABLE bets DROP CONSTRAINT ck_bet_type"))
        print("      dropped old ck_bet_type")
    except Exception as e:
        print(f"      WARNING: could not drop ck_bet_type: {e}")
        print("      (may not exist — continuing)")

    conn.execute(text(
        "ALTER TABLE bets ADD CONSTRAINT ck_bet_type "
        "CHECK (bet_type IN ('straight','spread','over_under','prop',"
        "                    'bench_battle','full_beef','the_lineup'))"
    ))
    print("      added ck_bet_type with 'the_lineup'")

    # --- 2c. rosters.slot: ADD COLUMN IF NOT EXISTS ---------------------------

    print("\n  2c. rosters.slot ...")
    if slot_exists:
        print("      column already exists — skipping")
    else:
        conn.execute(text(
            "ALTER TABLE rosters ADD COLUMN slot VARCHAR NULL"
        ))
        print("      added rosters.slot VARCHAR NULL")


# ── Step 3: Verify ─────────────────────────────────────────────────────────────

print()
print("=" * 60)
print("STEP 3  -- Verification")
print("=" * 60)

with engine.connect() as conn:
    rows_after = conn.execute(text("""
        SELECT conname, pg_get_constraintdef(oid) AS definition
        FROM   pg_constraint
        WHERE  conrelid = 'bets'::regclass
        AND    contype  = 'c'
        ORDER  BY conname
    """)).fetchall()

    print("\n  bets CHECK constraints after migration:")
    ok_status = False
    ok_type   = False
    for name, defn in rows_after:
        print(f"    {name:<25} {defn}")
        if name == "ck_bet_status" and "'push'" in defn:
            ok_status = True
        if name == "ck_bet_type" and "'the_lineup'" in defn:
            ok_type = True

    slot_after = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE  table_name  = 'rosters'
        AND    column_name = 'slot'
    """)).scalar()
    ok_slot = bool(slot_after)

    print()
    print(f"  ck_bet_status has 'push'        : {'OK' if ok_status else 'FAIL'}")
    print(f"  ck_bet_type has 'the_lineup'    : {'OK' if ok_type   else 'FAIL'}")
    print(f"  rosters.slot column exists      : {'OK' if ok_slot   else 'FAIL'}")
    print()

    all_ok = ok_status and ok_type and ok_slot
    if all_ok:
        print("  MIGRATION COMPLETE -- all checks passed.")
    else:
        print("  !! ONE OR MORE CHECKS FAILED -- review output above.")

print()
