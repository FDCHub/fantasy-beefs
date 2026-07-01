#!/usr/bin/env python3
"""
migrate_counter_offer_schema.py  --  Counter-offer DDL migration.

Adds two nullable columns to beef_challenges and adds 'countered' to the
ck_beef_status CHECK constraint:

  1. beef_challenges.countered_amount  DOUBLE PRECISION  NULL
  2. beef_challenges.countered_at      TIMESTAMP         NULL
  3. ck_beef_status: ('pending','countered','accepted','declined','expired')
     (was: 'pending','accepted','declined','expired')

SAFE:
  - Requires --confirm flag before any DDL executes.
  - Prints current constraint definition before altering.
  - ADD COLUMN steps are idempotent (skips if column already exists).
  - Constraint step is idempotent (skips if 'countered' already present).
  - Only targets Postgres. Exits early on SQLite.

USAGE:
  python migrate_counter_offer_schema.py              # dry-run
  python migrate_counter_offer_schema.py --confirm    # live write
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIRM = "--confirm" in sys.argv

print("\nmigrate_counter_offer_schema.py  --  counter-offer schema")
print(f"  mode : {'LIVE WRITE' if CONFIRM else 'DRY-RUN (pass --confirm to apply)'}\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if "sqlite" in db_url:
    print("!! ERROR: SQLite target detected.")
    print("   This migration uses Postgres DDL.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


# ── Step 1: Report current state ──────────────────────────────────────────────

print("=" * 64)
print("STEP 1  -- Current state in production")
print("=" * 64)

with engine.connect() as conn:
    # Check which columns already exist
    existing_cols = {
        row[0] for row in conn.execute(text("""
            SELECT column_name
            FROM   information_schema.columns
            WHERE  table_name = 'beef_challenges'
            AND    column_name IN ('countered_amount', 'countered_at')
        """)).fetchall()
    }

    # Check current ck_beef_status
    status_row = conn.execute(text("""
        SELECT pg_get_constraintdef(oid) AS definition
        FROM   pg_constraint
        WHERE  conrelid = 'beef_challenges'::regclass
        AND    conname  = 'ck_beef_status'
    """)).fetchone()
    current_status_defn = status_row[0] if status_row else None

print(f"\n  countered_amount column : {'EXISTS' if 'countered_amount' in existing_cols else 'MISSING'}")
print(f"  countered_at column     : {'EXISTS' if 'countered_at' in existing_cols else 'MISSING'}")
print(f"\n  ck_beef_status current  : {current_status_defn or 'NOT FOUND'}")

# ── Dry-run exit ──────────────────────────────────────────────────────────────

if not CONFIRM:
    print()
    print("DRY-RUN -- no DDL executed.")
    print("Re-run with --confirm to apply.\n")
    sys.exit(0)


# ── Step 2: Apply migrations ──────────────────────────────────────────────────

print()
print("=" * 64)
print("STEP 2  -- Applying DDL")
print("=" * 64)

with engine.begin() as conn:

    # --- 2a. countered_amount column -------------------------------------------

    print("\n  2a. beef_challenges.countered_amount ...")
    if "countered_amount" in existing_cols:
        print("      already exists -- skipping")
    else:
        conn.execute(text(
            "ALTER TABLE beef_challenges ADD COLUMN countered_amount DOUBLE PRECISION"
        ))
        print("      added DOUBLE PRECISION NULL")

    # --- 2b. countered_at column -----------------------------------------------

    print("\n  2b. beef_challenges.countered_at ...")
    if "countered_at" in existing_cols:
        print("      already exists -- skipping")
    else:
        conn.execute(text(
            "ALTER TABLE beef_challenges ADD COLUMN countered_at TIMESTAMP"
        ))
        print("      added TIMESTAMP NULL")

    # --- 2c. ck_beef_status constraint -----------------------------------------

    print("\n  2c. ck_beef_status ...")
    if current_status_defn and "'countered'" in current_status_defn:
        print("      already contains 'countered' -- skipping")
    else:
        try:
            conn.execute(text("ALTER TABLE beef_challenges DROP CONSTRAINT ck_beef_status"))
            print("      dropped old ck_beef_status")
        except Exception as e:
            print(f"      WARNING: could not drop ck_beef_status: {e}")

        conn.execute(text(
            "ALTER TABLE beef_challenges ADD CONSTRAINT ck_beef_status "
            "CHECK (status IN ('pending','countered','accepted','declined','expired'))"
        ))
        print("      added ck_beef_status -> (pending,countered,accepted,declined,expired)")


# ── Step 3: Verify ────────────────────────────────────────────────────────────

print()
print("=" * 64)
print("STEP 3  -- Verification")
print("=" * 64)

with engine.connect() as conn:
    after_cols = {
        row[0] for row in conn.execute(text("""
            SELECT column_name
            FROM   information_schema.columns
            WHERE  table_name = 'beef_challenges'
            AND    column_name IN ('countered_amount', 'countered_at')
        """)).fetchall()
    }
    after_status = conn.execute(text("""
        SELECT pg_get_constraintdef(oid) AS definition
        FROM   pg_constraint
        WHERE  conrelid = 'beef_challenges'::regclass
        AND    conname  = 'ck_beef_status'
    """)).fetchone()
    after_status_defn = after_status[0] if after_status else None

ok_col_amount  = "countered_amount" in after_cols
ok_col_at      = "countered_at"     in after_cols
ok_constraint  = after_status_defn is not None and "'countered'" in after_status_defn

print(f"\n  countered_amount column  : {'OK' if ok_col_amount else 'FAIL'}")
print(f"  countered_at column      : {'OK' if ok_col_at     else 'FAIL'}")
print(f"  ck_beef_status           : {after_status_defn or 'NOT FOUND'}")
print(f"  ck_beef_status countered : {'OK' if ok_constraint else 'FAIL'}")
print()

if ok_col_amount and ok_col_at and ok_constraint:
    print("  MIGRATION COMPLETE -- all checks passed.")
else:
    print("  !! ONE OR MORE CHECKS FAILED -- review output above.")
    sys.exit(1)

print()
