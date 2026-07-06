#!/usr/bin/env python3
"""
migrate_tx_type_pool_values.py  —  Production schema migration widening the
ck_tx_type CHECK constraint on the transactions table.

Production currently allows only: deposit, withdrawal, bet, payout.
Pool settlement (betting/pool_engine.py) writes 'pool_entry' and 'pool_payout'
transactions — both already used in code but never added to the production
constraint. Widens the allowed set to all six values.

Postgres cannot alter a CHECK constraint in place — this drops ck_tx_type and
re-adds it with the widened value list, both inside a single transaction
(engine.begin()), so the transactions table is never left without the
constraint even if the ADD CONSTRAINT step fails.

SAFE:
  - DROP and ADD CONSTRAINT run inside one transaction — they commit or roll
    back together, never leaving the table constraint-less.
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or does
    not point at a Postgres instance.
  - No data changes — this is a constraint-only DDL migration.

USAGE:
  python db/migrations/migrate_tx_type_pool_values.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_tx_type_pool_values.py  --  ck_tx_type constraint widening\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


# ── Step 1: Widen ck_tx_type ──────────────────────────────────────────────────

print("=" * 60)
print("STEP 1  -- Widening ck_tx_type on transactions")
print("=" * 60)

try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE transactions DROP CONSTRAINT ck_tx_type"))
        conn.execute(text(
            "ALTER TABLE transactions ADD CONSTRAINT ck_tx_type "
            "CHECK (type IN ('deposit','withdrawal','bet','payout','pool_entry','pool_payout'))"
        ))
    print("\n  ck_tx_type dropped and re-added with pool_entry, pool_payout")
except Exception as e:
    print(f"\n!! ERROR: constraint migration failed: {e}")
    sys.exit(1)


# ── Step 2: Verify ───────────────────────────────────────────────────────────

print()
print("=" * 60)
print("STEP 2  -- Verification")
print("=" * 60)

try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE conrelid = 'transactions'::regclass AND conname = 'ck_tx_type'
        """)).scalar()
except Exception as e:
    print(f"\n!! ERROR: verification query failed: {e}")
    sys.exit(1)

print()
if result and "pool_entry" in result and "pool_payout" in result:
    print(f"  ck_tx_type confirmed: {result}")
    print("  MIGRATION COMPLETE -- constraint widened.\n")
else:
    print(f"!! ERROR: ck_tx_type does not include pool_entry/pool_payout after migration: {result}")
    sys.exit(1)
