#!/usr/bin/env python3
"""
migrate_settlement_recovery_audit.py  —  Production schema migration creating
the settlement_recovery_audit table in support of FR-8.7 §5b (authorized
week-settlement recovery).

recover_week() writes one immutable audit row per authorized recovery: who
authorized it, the operator-supplied process-exit evidence, and the structured
pre-recovery facts observed under the week_settlements row lock. The table is
append-only by convention — code INSERTs, never updates or deletes. This
migration only CREATES the table; it does not touch week_settlements or any
other table.

Creates (see db/schema.py SettlementRecoveryAudit model):
  settlement_recovery_audit
    id                            SERIAL PRIMARY KEY
    league_id                     INTEGER REFERENCES leagues(id) NOT NULL
    week                          INTEGER NOT NULL
    actor                         VARCHAR NOT NULL
    exit_evidence                 JSONB NOT NULL     ({category, detail})
    observed_pre_state            JSONB NOT NULL     (structured locked facts)
    recovered_at                  TIMESTAMPTZ NOT NULL
    recovery_token_fingerprint    VARCHAR NOT NULL
    prior_recovery_token_present  BOOLEAN NOT NULL

JSON columns — exit_evidence / observed_pre_state are JSONB (this migration is
Postgres-only, so JSONB is correct here). The db/schema.py model declares them
as JSON().with_variant(JSONB(), "postgresql"), which renders JSONB on Postgres
and degrades to a TEXT-backed JSON round-trip on the SQLite (test) path. Python
dicts are stored directly — no json.dumps.

SAFE:
  - Additive only. Creates one new table; never drops or modifies any existing
    table or column.
  - Idempotent: checks information_schema.tables for 'settlement_recovery_audit'
    BEFORE issuing CREATE TABLE. Skips creation (exit 0) if it already exists,
    so running this twice does nothing wrong.
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or does
    not point at a Postgres instance.
  - The CREATE TABLE runs inside ONE transaction (engine.begin()) — Postgres
    DDL is fully transactional, so any failure rolls back cleanly, never
    leaving a half-created table.
  - Does NOT touch any other table or column.

USAGE:
  python db/migrations/migrate_settlement_recovery_audit.py

REVERSIBILITY:
  A downgrade() function is defined below that DROPs the table. It is NOT
  auto-invoked — running this script performs the create only. To reverse,
  open a Python shell and call downgrade() explicitly.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_settlement_recovery_audit.py  --  settlement_recovery_audit table migration\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")

_TABLE = "settlement_recovery_audit"


def _table_exists(conn) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = :t
        )
    """), {"t": _TABLE}).scalar()


_CREATE_SQL = """
    CREATE TABLE settlement_recovery_audit (
        id                            SERIAL PRIMARY KEY,
        league_id                     INTEGER REFERENCES leagues(id) NOT NULL,
        week                          INTEGER NOT NULL,
        actor                         VARCHAR NOT NULL,
        exit_evidence                 JSONB NOT NULL,
        observed_pre_state            JSONB NOT NULL,
        recovered_at                  TIMESTAMPTZ NOT NULL,
        recovery_token_fingerprint    VARCHAR NOT NULL,
        prior_recovery_token_present  BOOLEAN NOT NULL
    )
"""


def downgrade() -> None:
    """Reverse this migration: DROP the settlement_recovery_audit table. NOT
    auto-invoked — runs only when called explicitly (e.g. from a Python shell).
    Shares the same Postgres-only guard, is idempotent (only drops the table if
    it is actually present), and runs inside a single engine.begin() transaction.
    Never touches any other table."""
    if not os.environ.get("DATABASE_URL") or "postgres" not in str(engine.url):
        print("!! ERROR: Postgres target not detected — refusing to downgrade.")
        return

    with engine.connect() as conn:
        exists = _table_exists(conn)
    if not exists:
        print(f"  {_TABLE} does not exist -- nothing to downgrade.")
        return

    try:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE {_TABLE}"))
            print(f"  {_TABLE} dropped")
    except Exception as e:
        print(f"!! ERROR: downgrade failed and the entire transaction was rolled back: {e}")
        print("   The table was not dropped.")
        return

    print("  DOWNGRADE COMPLETE.")


# ── Step 1: before-state ──────────────────────────────────────────────────────

print("=" * 60)
print("STEP 1  -- Current state (before)")
print("=" * 60)

with engine.connect() as conn:
    already = _table_exists(conn)
print(f"\n  {_TABLE} exists : {already}")

if already:
    print(f"\n  {_TABLE} already exists -- nothing to do.")
    sys.exit(0)


# ── Step 2: create the table (single transaction) ─────────────────────────────

print()
print("=" * 60)
print("STEP 2  -- Creating table")
print("=" * 60)

try:
    with engine.begin() as conn:
        conn.execute(text(_CREATE_SQL))
        print(f"\n  {_TABLE} created")
except Exception as e:
    print(f"\n!! ERROR: migration failed and the entire transaction was rolled back: {e}")
    print("   No table was created.")
    sys.exit(1)


# ── Step 3: after-state + verification ────────────────────────────────────────

print()
print("=" * 60)
print("STEP 3  -- Verification (after)")
print("=" * 60)

with engine.connect() as conn:
    now_exists = _table_exists(conn)
print(f"\n  {_TABLE} exists : {now_exists}")

if not now_exists:
    print(f"\n!! ERROR: {_TABLE} still missing after CREATE TABLE — unexpected.")
    sys.exit(1)

from db.schema import SessionLocal, SettlementRecoveryAudit

with SessionLocal() as db:
    n = db.query(SettlementRecoveryAudit).count()
    print(f"\n  verified via ORM round-trip: {_TABLE} rows = {n}")

print("\n  MIGRATION COMPLETE.\n")
