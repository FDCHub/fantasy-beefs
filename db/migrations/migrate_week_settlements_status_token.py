#!/usr/bin/env python3
"""
migrate_week_settlements_status_token.py  —  Production schema migration
adding two columns to week_settlements in support of FR-8.7 (claim-first
settlement with explicit lifecycle status + crash-recovery token).

The week_settlements table today (see db/schema.py WeekSettlement model)
has only id, league_id, week, settled, settled_at. FR-8.7 introduces an
explicit settlement lifecycle status and a recovery token so a crashed
payout loop is detectable and resumable, rather than the current
"settled=True is written before payouts run, with no crash-recovery"
gap. This migration only ADDS the two columns; it does not change the
run-once claim mechanism, does not touch uq_week_settlement_league_week,
and does not drop or alter settled/settled_at.

Adds (see db/schema.py WeekSettlement model):
  week_settlements.status          VARCHAR NOT NULL DEFAULT 'CLAIMED'
  week_settlements.recovery_token  VARCHAR, nullable, no default

status — NOT NULL DEFAULT 'CLAIMED', added in a single ADD COLUMN
statement. Confirmed production is PostgreSQL (MIG-1, Opus review),
well past the version 11 threshold where Postgres applies a NOT NULL
DEFAULT to existing rows atomically as a metadata-only operation — no
table rewrite, no separate backfill UPDATE, no transient-NULL window to
protect via the transaction lock. 'CLAIMED' is the conservative,
fail-safe default: an existing settled=True row cannot PROVE its Phase 2
payout loop completed, so it must NOT be auto-upgraded to 'COMPLETED'
(that would permanently suppress settlement on an unprovable assertion).
Defaulting to 'CLAIMED' forces any such row through the honest lifecycle
— completion or manual recovery — rather than trusting a boolean that
predates the CLAIMED/COMPLETED distinction. This holds even for a row
that appears between migration and application deployment.

recovery_token — VARCHAR NULL, added with no default and no backfill.
Existing rows get NULL, which is the fully handled "no recovery token
recorded" state at read time.

SAFE:
  - Additive only. Never drops or modifies any existing column.
  - Never touches uq_week_settlement_league_week, settled, or settled_at.
  - Idempotent: checks information_schema.columns for each target column
    BEFORE issuing its ALTER TABLE. Skips a column's ALTER entirely if
    it's already present, so running this twice (or against a
    week_settlements table that already has one of the two columns but
    not the other) does nothing wrong.
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or
    does not point at a Postgres instance.
  - Both columns' ADD COLUMN statements run inside ONE transaction
    (engine.begin()) — Postgres DDL is fully transactional, so any
    failure partway through rolls back everything in this script (MIG-3),
    never leaving a half-added column.
  - Does NOT touch any other table or column.

USAGE:
  python db/migrations/migrate_week_settlements_status_token.py

REVERSIBILITY:
  A downgrade() function is defined below that drops the two columns.
  It is NOT auto-invoked — running this script performs the upgrade only.
  To reverse, open a Python shell and call downgrade() explicitly. See
  its docstring for the guard it shares with the upgrade path.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_week_settlements_status_token.py  --  week_settlements status / recovery_token column migration\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


def _existing_week_settlements_columns(conn) -> set[str]:
    rows = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'week_settlements'
    """)).fetchall()
    return {r[0] for r in rows}


def downgrade() -> None:
    """Reverse this migration: drop status and recovery_token from
    week_settlements. NOT auto-invoked — this runs only when called
    explicitly (e.g. from a Python shell). Shares the same Postgres-only
    guard as the upgrade path, is idempotent (only drops a column that is
    actually present), and drops both inside a single engine.begin()
    transaction so a partial failure rolls back cleanly. Never touches
    settled, settled_at, or uq_week_settlement_league_week."""
    if not os.environ.get("DATABASE_URL") or "postgres" not in str(engine.url):
        print("!! ERROR: Postgres target not detected — refusing to downgrade.")
        return

    with engine.connect() as conn:
        cols = _existing_week_settlements_columns(conn)
    drop_status = "status" in cols
    drop_token = "recovery_token" in cols

    if not drop_status and not drop_token:
        print("  Neither column present -- nothing to downgrade.")
        return

    try:
        with engine.begin() as conn:
            if drop_status:
                conn.execute(text("ALTER TABLE week_settlements DROP COLUMN status"))
                print("  week_settlements.status dropped")
            if drop_token:
                conn.execute(text("ALTER TABLE week_settlements DROP COLUMN recovery_token"))
                print("  week_settlements.recovery_token dropped")
    except Exception as e:
        print(f"!! ERROR: downgrade failed and the entire transaction was rolled back: {e}")
        print("   No columns were dropped or changed.")
        return

    print("  DOWNGRADE COMPLETE.")


# ── Step 1: before-state ──────────────────────────────────────────────────────

print("=" * 60)
print("STEP 1  -- Current week_settlements columns (before)")
print("=" * 60)

with engine.connect() as conn:
    before_cols = _existing_week_settlements_columns(conn)
print(f"\n  {sorted(before_cols)}")

need_status = "status" not in before_cols
need_recovery_token = "recovery_token" not in before_cols

if not need_status and not need_recovery_token:
    print("\n  Both target columns already exist -- nothing to do.")
    sys.exit(0)

print(f"\n  status needs adding         : {need_status}")
print(f"  recovery_token needs adding : {need_recovery_token}")


# ── Step 2: add the columns (additive, single transaction) ───────────────────

print()
print("=" * 60)
print("STEP 2  -- Adding missing column(s)")
print("=" * 60)

try:
    with engine.begin() as conn:
        if need_status:
            # Single-statement NOT NULL DEFAULT add (MIG-1) — Postgres 11+
            # applies this to existing rows atomically as a metadata-only
            # operation, no separate backfill UPDATE needed.
            conn.execute(text(
                "ALTER TABLE week_settlements ADD COLUMN status "
                "VARCHAR NOT NULL DEFAULT 'CLAIMED'"
            ))
            print("\n  week_settlements.status added: NOT NULL DEFAULT 'CLAIMED', "
                  "backfilled on existing rows atomically")

        if need_recovery_token:
            conn.execute(text(
                "ALTER TABLE week_settlements ADD COLUMN recovery_token VARCHAR"
            ))
            print("  week_settlements.recovery_token added (nullable, no default, no backfill)")
except Exception as e:
    print(f"\n!! ERROR: migration failed and the entire transaction was rolled back: {e}")
    print("   No columns were added or changed.")
    sys.exit(1)


# ── Step 3: after-state + verification ────────────────────────────────────────

print()
print("=" * 60)
print("STEP 3  -- Verification (after)")
print("=" * 60)

with engine.connect() as conn:
    after_cols = _existing_week_settlements_columns(conn)
print(f"\n  {sorted(after_cols)}")

missing = {"status", "recovery_token"} - after_cols
if missing:
    print(f"\n!! ERROR: still missing after migration: {sorted(missing)}")
    sys.exit(1)

from db.schema import SessionLocal, WeekSettlement

with SessionLocal() as db:
    n = db.query(WeekSettlement).count()
    print(f"\n  week_settlements rows: {n}")
    ws = db.query(WeekSettlement).first()
    if ws:
        _ = ws.status
        _ = ws.recovery_token
        print(f"  verified via ORM on week_settlement #{ws.id}: "
              f"status={ws.status!r}, recovery_token={ws.recovery_token!r}")

print("\n  MIGRATION COMPLETE.\n")
