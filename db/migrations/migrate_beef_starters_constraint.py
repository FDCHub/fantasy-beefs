#!/usr/bin/env python3
"""
migrate_beef_starters_constraint.py  —  Production schema migration for
beef_starters uniqueness.

Two stages, run in a single transaction:
  1. DELETE duplicate beef_starters rows, keeping the lowest id per
     (beef_challenge_id, team_id, player_id).
  2. ALTER TABLE beef_starters ADD CONSTRAINT uq_beef_starters
     UNIQUE (beef_challenge_id, team_id, player_id).

SAFE:
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or does
    not point at a Postgres instance.
  - Stage 1 is safe to re-run — a table with no duplicates means zero rows
    deleted.
  - Stage 2 checks for the constraint's existence first and skips if it's
    already there, so a second run is a no-op rather than an error.
  - Both stages run in one transaction — either both succeed or neither is
    committed.

USAGE:
  python db/migrations/migrate_beef_starters_constraint.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_beef_starters_constraint.py  --  beef_starters uniqueness migration\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


try:
    with engine.begin() as conn:

        # ── Stage 1: Delete duplicate rows, keeping lowest id per triple ─────
        print("=" * 60)
        print("STAGE 1  -- Removing duplicate beef_starters rows")
        print("=" * 60)

        result = conn.execute(text("""
            DELETE FROM beef_starters a
            USING beef_starters b
            WHERE a.id > b.id
              AND a.beef_challenge_id = b.beef_challenge_id
              AND a.team_id           = b.team_id
              AND a.player_id         = b.player_id
        """))
        print(f"\n  duplicate rows removed: {result.rowcount}")

        # ── Stage 2: Add the unique constraint ───────────────────────────────
        print()
        print("=" * 60)
        print("STAGE 2  -- Adding uq_beef_starters constraint")
        print("=" * 60)

        constraint_exists = conn.execute(text("""
            SELECT COUNT(*) FROM pg_constraint WHERE conname = 'uq_beef_starters'
        """)).scalar()

        if constraint_exists:
            print("\n  uq_beef_starters already exists — skipping")
        else:
            conn.execute(text("""
                ALTER TABLE beef_starters
                ADD CONSTRAINT uq_beef_starters
                UNIQUE (beef_challenge_id, team_id, player_id)
            """))
            print("\n  uq_beef_starters constraint added")

except Exception as e:
    print(f"\n!! ERROR: migration failed: {e}")
    sys.exit(1)


# ── Verify ────────────────────────────────────────────────────────────────────

print()
print("=" * 60)
print("VERIFY  -- Confirming uq_beef_starters constraint exists")
print("=" * 60)

try:
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT conname FROM pg_constraint WHERE conname = 'uq_beef_starters'
        """)).scalar()
except Exception as e:
    print(f"\n!! ERROR: verification query failed: {e}")
    sys.exit(1)

print()
if result:
    print(f"  uq_beef_starters constraint confirmed: {result}")
    print("  MIGRATION COMPLETE -- constraint exists.\n")
else:
    print("!! ERROR: uq_beef_starters constraint not found after migration — unexpected.")
    sys.exit(1)
