#!/usr/bin/env python3
"""
migrate_remove_bench_parlay_constraints.py  —  Production DDL migration.

Removes retired bet types from two CHECK constraints:
  1. bets.ck_bet_type        — drop 'bench_battle' and 'full_beef'
                               leaving ('straight','spread','over_under','prop','the_lineup')
  2. beef_challenges.ck_beef_bet_type — drop 'bench_battle'
                               leaving ('straight','spread','over_under','prop')

SAFE:
  - Requires --confirm flag before any DDL executes.
  - Prints current constraint definitions before altering.
  - Each step is idempotent: skips with a warning if the constraint
    is already at the target state.
  - Only targets Postgres. Exits early on SQLite.

USAGE:
  python migrate_remove_bench_parlay_constraints.py              # dry-run
  python migrate_remove_bench_parlay_constraints.py --confirm    # live write
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIRM = "--confirm" in sys.argv

print("\nmigrate_remove_bench_parlay_constraints.py  --  bench_battle/full_beef DDL cleanup")
print(f"  mode : {'LIVE WRITE' if CONFIRM else 'DRY-RUN (pass --confirm to apply)'}\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if "sqlite" in db_url:
    print("!! ERROR: SQLite target detected.")
    print("   This migration uses Postgres DDL (DROP CONSTRAINT / ADD CONSTRAINT).")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


# ── Step 1: Print current constraint definitions ───────────────────────────────

print("=" * 64)
print("STEP 1  -- Current constraint definitions in production")
print("=" * 64)

TARGET_CONSTRAINTS = ("ck_bet_type", "ck_beef_bet_type")

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT conname, pg_get_constraintdef(oid) AS definition
        FROM   pg_constraint
        WHERE  conrelid IN ('bets'::regclass, 'beef_challenges'::regclass)
        AND    conname   IN ('ck_bet_type', 'ck_beef_bet_type')
        ORDER  BY conname
    """)).fetchall()

current = {name: defn for name, defn in rows}

for name in TARGET_CONSTRAINTS:
    if name in current:
        print(f"\n  {name}:")
        print(f"    {current[name]}")
    else:
        print(f"\n  {name}: NOT FOUND (may have already been dropped)")

# ── Dry-run exit ───────────────────────────────────────────────────────────────

if not CONFIRM:
    print()
    print("DRY-RUN -- no DDL executed.")
    print("Re-run with --confirm to apply.\n")
    sys.exit(0)


# ── Step 2: Apply migrations ───────────────────────────────────────────────────

print()
print("=" * 64)
print("STEP 2  -- Applying DDL")
print("=" * 64)

NEW_BET_TYPE = (
    "CHECK (bet_type IN ('straight','spread','over_under','prop','the_lineup'))"
)
NEW_BEEF_BET_TYPE = (
    "CHECK (bet_type IN ('straight','spread','over_under','prop'))"
)

with engine.begin() as conn:

    # --- 2a. ck_bet_type on bets ------------------------------------------

    print("\n  2a. bets.ck_bet_type ...")
    defn = current.get("ck_bet_type", "")
    if "bench_battle" not in defn and "full_beef" not in defn:
        print("      already clean — skipping (no bench_battle or full_beef found)")
    else:
        try:
            conn.execute(text("ALTER TABLE bets DROP CONSTRAINT ck_bet_type"))
            print("      dropped old ck_bet_type")
        except Exception as e:
            print(f"      WARNING: could not drop ck_bet_type: {e}")

        conn.execute(text(
            "ALTER TABLE bets ADD CONSTRAINT ck_bet_type "
            "CHECK (bet_type IN ('straight','spread','over_under','prop','the_lineup'))"
        ))
        print("      added ck_bet_type  -> (straight,spread,over_under,prop,the_lineup)")

    # --- 2b. ck_beef_bet_type on beef_challenges --------------------------

    print("\n  2b. beef_challenges.ck_beef_bet_type ...")
    defn = current.get("ck_beef_bet_type", "")
    if "bench_battle" not in defn:
        print("      already clean — skipping (no bench_battle found)")
    else:
        try:
            conn.execute(text("ALTER TABLE beef_challenges DROP CONSTRAINT ck_beef_bet_type"))
            print("      dropped old ck_beef_bet_type")
        except Exception as e:
            print(f"      WARNING: could not drop ck_beef_bet_type: {e}")

        conn.execute(text(
            "ALTER TABLE beef_challenges ADD CONSTRAINT ck_beef_bet_type "
            "CHECK (bet_type IN ('straight','spread','over_under','prop'))"
        ))
        print("      added ck_beef_bet_type  -> (straight,spread,over_under,prop)")


# ── Step 3: Verify ─────────────────────────────────────────────────────────────

print()
print("=" * 64)
print("STEP 3  -- Verification")
print("=" * 64)

with engine.connect() as conn:
    rows_after = conn.execute(text("""
        SELECT conname, pg_get_constraintdef(oid) AS definition
        FROM   pg_constraint
        WHERE  conrelid IN ('bets'::regclass, 'beef_challenges'::regclass)
        AND    conname   IN ('ck_bet_type', 'ck_beef_bet_type')
        ORDER  BY conname
    """)).fetchall()

print("\n  Constraints after migration:")
ok_bet_type       = False
ok_beef_bet_type  = False

for name, defn in rows_after:
    print(f"    {name:<25} {defn}")
    if name == "ck_bet_type" and "bench_battle" not in defn and "full_beef" not in defn:
        ok_bet_type = True
    if name == "ck_beef_bet_type" and "bench_battle" not in defn:
        ok_beef_bet_type = True

print()
print(f"  ck_bet_type clean (no bench_battle/full_beef) : {'OK' if ok_bet_type  else 'FAIL'}")
print(f"  ck_beef_bet_type clean (no bench_battle)      : {'OK' if ok_beef_bet_type else 'FAIL'}")
print()

if ok_bet_type and ok_beef_bet_type:
    print("  MIGRATION COMPLETE -- all checks passed.")
else:
    print("  !! ONE OR MORE CHECKS FAILED -- review output above.")
    sys.exit(1)

print()
