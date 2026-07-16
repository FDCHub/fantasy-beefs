#!/usr/bin/env python3
"""
migrate_players_yahoo_id.py  —  Production schema migration adding a
yahoo_id column to players (FR-7.30). The players table currently has only
id, name, position, nfl_team — its ONLY external join key is name, which is
why every Yahoo->DB player resolution today is fragile string matching
(player_map[name.lower()]). This column gives players a stable Yahoo
identity so a future sync/backfill can key on the Yahoo player_id the
roster fetch already returns, instead of name.

Adds (see db/schema.py Player model):
  players.yahoo_id   VARCHAR, nullable, UNIQUE (via named unique index)

NULL semantics — explicit and depended upon:
  yahoo_id is nullable and stays NULL for any row not yet resolved to a
  Yahoo id. The backfill (a SEPARATE script, FR-7.30 step 3) is name-based
  and, per recon, resolves 179 of the 180 existing rows — exactly one row
  (a Josh/Joshua spelling variance) is expected to remain NULL. Postgres
  permits MULTIPLE NULLs in a UNIQUE index, so a unique constraint on
  yahoo_id does NOT block that lingering NULL row (or any future
  unresolved row). This design relies on that Postgres semantics.

SAFE:
  - Additive only. Never drops or modifies any existing column. No data
    migration and NO backfill — the backfill is a separate script (step 3).
  - Idempotent: checks information_schema.columns for table_name='players'
    BEFORE issuing any DDL. Skips entirely if yahoo_id is already present.
    (The column ADD and the unique index CREATE run in ONE transaction, so
    "column present" implies "index present" — checking the column alone is
    sufficient to detect an already-migrated table.)
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or
    does not point at a Postgres instance.
  - Both DDL statements run inside ONE transaction (engine.begin()) —
    Postgres DDL is fully transactional, so any failure partway through
    rolls back everything in this script, never leaving a half-migrated
    table (a column with no unique index).
  - Does NOT touch any other table or column.

USAGE:
  python db/migrations/migrate_players_yahoo_id.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_players_yahoo_id.py  --  players.yahoo_id column migration (FR-7.30)\n")

from sqlalchemy import text
from db.schema import engine

_INDEX_NAME = "ix_players_yahoo_id_unique"

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


def _existing_players_columns(conn) -> set[str]:
    rows = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'players'
    """)).fetchall()
    return {r[0] for r in rows}


# ── Step 1: before-state ──────────────────────────────────────────────────────

print("=" * 60)
print("STEP 1  -- Current players columns (before)")
print("=" * 60)

with engine.connect() as conn:
    before_cols = _existing_players_columns(conn)
print(f"\n  {sorted(before_cols)}")

need_yahoo_id = "yahoo_id" not in before_cols

if not need_yahoo_id:
    print("\n  players.yahoo_id already exists -- nothing to do.")
    sys.exit(0)

print(f"\n  yahoo_id needs adding : {need_yahoo_id}")


# ── Step 2: add the column + unique index (additive, single transaction) ─────

print()
print("=" * 60)
print("STEP 2  -- Adding players.yahoo_id + unique index")
print("=" * 60)

try:
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE players ADD COLUMN yahoo_id VARCHAR"
        ))
        print("\n  players.yahoo_id added (VARCHAR, nullable, no default, no backfill)")

        # Named unique index (not an inline UNIQUE constraint) so the name is
        # explicit and NULL semantics stay clear. Postgres allows multiple
        # NULLs in a unique index, so unresolved rows (expected: ~1) coexist.
        conn.execute(text(
            f"CREATE UNIQUE INDEX {_INDEX_NAME} ON players (yahoo_id)"
        ))
        print(f"  {_INDEX_NAME} created: UNIQUE on players (yahoo_id), "
              "multiple NULLs permitted")
except Exception as e:
    print(f"\n!! ERROR: migration failed and the entire transaction was rolled back: {e}")
    print("   No column or index was added or changed.")
    sys.exit(1)


# ── Step 3: after-state + verification ────────────────────────────────────────

print()
print("=" * 60)
print("STEP 3  -- Verification (after)")
print("=" * 60)

with engine.connect() as conn:
    after_cols = _existing_players_columns(conn)
    index_present = conn.execute(text("""
        SELECT COUNT(*) FROM pg_indexes
        WHERE tablename = 'players' AND indexname = :name
    """), {"name": _INDEX_NAME}).scalar()
print(f"\n  {sorted(after_cols)}")

if "yahoo_id" not in after_cols:
    print("\n!! ERROR: players.yahoo_id still missing after migration.")
    sys.exit(1)
if not index_present:
    print(f"\n!! ERROR: unique index {_INDEX_NAME} missing after migration.")
    sys.exit(1)
print(f"  unique index {_INDEX_NAME}: present")

from db.schema import SessionLocal, Player

with SessionLocal() as db:
    n = db.query(Player).count()
    print(f"\n  players rows: {n}")
    player = db.query(Player).first()
    if player:
        _ = player.yahoo_id
        print(f"  verified via ORM on player #{player.id}: "
              f"yahoo_id={player.yahoo_id!r}")

print("\n  MIGRATION COMPLETE.\n")
