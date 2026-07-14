#!/usr/bin/env python3
"""
migrate_remove_prop_beef_constraint.py  —  Production DDL migration.

Removes the retired 'prop' bet type from one CHECK constraint:
  beef_challenges.ck_beef_bet_type — drop 'prop'
                                     leaving ('straight','spread','over_under')

bets.ck_bet_type is deliberately NOT touched by this script — prop bets
placed via betting/bet_engine.py's place_prop_bet() are retired at the
placement layer (that function now always rejects), but Bet still needs
to store any historical prop rows without a schema fight. Confirmed via
direct production query before writing this script: bets has 0 rows of
any type and beef_challenges has 0 rows of any type — there is nothing
that would violate the tightened beef_challenges constraint, and no
'prop' row exists anywhere to protect. If that ever changes before this
runs, re-run the same existence check first.

Same style/precedent as migrate_remove_bench_parlay_constraints.py.

SAFE:
  - Requires --confirm flag before any DDL executes.
  - Prints current constraint definition before altering.
  - Idempotent: skips with a warning if the constraint is already at the
    target state.
  - Only targets Postgres. Exits early on SQLite.

USAGE:
  python migrate_remove_prop_beef_constraint.py              # dry-run
  python migrate_remove_prop_beef_constraint.py --confirm    # live write
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIRM = "--confirm" in sys.argv

print("\nmigrate_remove_prop_beef_constraint.py  --  beef_challenges.ck_beef_bet_type 'prop' removal")
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


# ── Step 1: Print current constraint definition + existence check ─────────────

print("=" * 64)
print("STEP 1  -- Current constraint definition + existing-row check")
print("=" * 64)

with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT conname, pg_get_constraintdef(oid) AS definition
        FROM   pg_constraint
        WHERE  conrelid = 'beef_challenges'::regclass
        AND    conname   = 'ck_beef_bet_type'
    """)).fetchall()

    current = {name: defn for name, defn in rows}

    prop_count = conn.execute(text(
        "SELECT COUNT(*) FROM beef_challenges WHERE bet_type = 'prop'"
    )).scalar()

if "ck_beef_bet_type" in current:
    print(f"\n  ck_beef_bet_type:")
    print(f"    {current['ck_beef_bet_type']}")
else:
    print(f"\n  ck_beef_bet_type: NOT FOUND (may have already been dropped)")

print(f"\n  beef_challenges rows with bet_type='prop': {prop_count}")
if prop_count > 0:
    print("\n!! ERROR: existing 'prop' rows found in beef_challenges. Adding the")
    print("   tightened constraint (ADD CONSTRAINT validates existing rows by")
    print("   default in Postgres) would fail against them. This migration")
    print("   refuses to proceed — decide what to do with those rows first,")
    print("   this is a real finding, not a mechanical edit anymore.")
    sys.exit(1)

# ── Dry-run exit ───────────────────────────────────────────────────────────────

if not CONFIRM:
    print()
    print("DRY-RUN -- no DDL executed.")
    print("Re-run with --confirm to apply.\n")
    sys.exit(0)


# ── Step 2: Apply migration ─────────────────────────────────────────────────────

print()
print("=" * 64)
print("STEP 2  -- Applying DDL")
print("=" * 64)

NEW_BEEF_BET_TYPE = (
    "CHECK (bet_type IN ('straight','spread','over_under'))"
)

with engine.begin() as conn:
    print("\n  beef_challenges.ck_beef_bet_type ...")
    defn = current.get("ck_beef_bet_type", "")
    if "prop" not in defn:
        print("      already clean — skipping (no 'prop' found)")
    else:
        try:
            conn.execute(text("ALTER TABLE beef_challenges DROP CONSTRAINT ck_beef_bet_type"))
            print("      dropped old ck_beef_bet_type")
        except Exception as e:
            print(f"      WARNING: could not drop ck_beef_bet_type: {e}")

        conn.execute(text(
            "ALTER TABLE beef_challenges ADD CONSTRAINT ck_beef_bet_type "
            "CHECK (bet_type IN ('straight','spread','over_under'))"
        ))
        print("      added ck_beef_bet_type  -> (straight,spread,over_under)")


# ── Step 3: Verify ─────────────────────────────────────────────────────────────

print()
print("=" * 64)
print("STEP 3  -- Verification")
print("=" * 64)

with engine.connect() as conn:
    rows_after = conn.execute(text("""
        SELECT conname, pg_get_constraintdef(oid) AS definition
        FROM   pg_constraint
        WHERE  conrelid = 'beef_challenges'::regclass
        AND    conname   = 'ck_beef_bet_type'
    """)).fetchall()

print("\n  Constraint after migration:")
ok_beef_bet_type = False

for name, defn in rows_after:
    print(f"    {name:<25} {defn}")
    if name == "ck_beef_bet_type" and "prop" not in defn:
        ok_beef_bet_type = True

print()
print(f"  ck_beef_bet_type clean (no 'prop') : {'OK' if ok_beef_bet_type else 'FAIL'}")
print()

if ok_beef_bet_type:
    print("  MIGRATION COMPLETE -- check passed.")
else:
    print("  !! CHECK FAILED -- review output above.")
    sys.exit(1)

print()
