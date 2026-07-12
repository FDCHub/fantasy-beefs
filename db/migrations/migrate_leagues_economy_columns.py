#!/usr/bin/env python3
"""
migrate_leagues_economy_columns.py  —  Production schema migration adding
two columns to leagues that exist in db/schema.py but were never shipped
to production — confirmed via direct query (check_leagues_columns.py)
against production Postgres: production's leagues table has only
id, season, name, projection_source. This gap is why the current deploy
fails its health check with UndefinedColumn the moment any code path
touches League.economy_stop_weekly_min_cents or
League.buyin_enforcement_active.

MONEY-PATH: both columns are the sole activation source for real money
gates —
  economy_stop_weekly_min_cents selects the league's Discrete-Stop Economy
  Table entry (payments/economy_config.py), and
  buyin_enforcement_active is the commissioner-set flag that turns the
  buy-in enforcement gate on or off (payments/stripe_connect.py).
DO NOT RUN THIS AGAINST PRODUCTION WITHOUT SIGN-OFF. This script only
adds the columns — it does not flip either one to an active value for
any league.

Adds (see db/schema.py League model):
  leagues.economy_stop_weekly_min_cents   INTEGER, nullable, no default
  leagues.buyin_enforcement_active        BOOLEAN NOT NULL DEFAULT FALSE

economy_stop_weekly_min_cents — NULL semantics, confirmed against
db/schema.py's own comment (line 54-57) and
payments/economy_config.py's get_league_economy_stop(), NOT assumed:
  NULL does NOT mean "the economy stop system is inactive" for that
  league — get_league_economy_stop() treats NULL as "unconfigured" and
  falls back to DEFAULT_STOP (weekly_min_cents=1000, i.e. $10/week).
  Every league is always on SOME stop; NULL just means "on the default
  one," not "opted out." No backfill needed either way — existing rows
  get NULL, which is a fully handled, safe state at read time.

buyin_enforcement_active — NOT NULL DEFAULT FALSE, added in a single
ADD COLUMN statement. Confirmed production is PostgreSQL 18.4 (MIG-1,
Opus review), well past the version 11 threshold where Postgres applies
a NOT NULL DEFAULT to existing rows atomically as a metadata-only
operation — no table rewrite, no separate backfill UPDATE, no
transient-NULL window to protect via the transaction lock. FALSE
matches the real current behavior of every league in production today
(the buy-in gate has been inactive for every league since B1 stopped
writing to LeagueTreasury) — this migration changes nothing observable
for existing leagues the instant it deploys.

SAFE:
  - Additive only. Never drops or modifies any existing column.
  - Idempotent: checks information_schema.columns for each target column
    BEFORE issuing its ALTER TABLE — same query pattern as
    check_leagues_columns.py, the script used to diagnose this gap.
    Skips a column's ALTER entirely if it's already present, so running
    this twice (or against a leagues table that already has one of the
    two columns but not the other) does nothing wrong.
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or
    does not point at a Postgres instance.
  - Both columns' ADD COLUMN statements run inside ONE transaction
    (engine.begin()) — Postgres DDL is fully transactional, so any
    failure partway through rolls back everything in this script (MIG-3),
    never leaving a half-added column.
  - Does NOT touch any other table or column.

USAGE:
  python db/migrations/migrate_leagues_economy_columns.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_leagues_economy_columns.py  --  leagues economy-stop / buyin-enforcement column migration\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


def _existing_leagues_columns(conn) -> set[str]:
    rows = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'leagues'
    """)).fetchall()
    return {r[0] for r in rows}


# ── Step 1: before-state ──────────────────────────────────────────────────────

print("=" * 60)
print("STEP 1  -- Current leagues columns (before)")
print("=" * 60)

with engine.connect() as conn:
    before_cols = _existing_leagues_columns(conn)
print(f"\n  {sorted(before_cols)}")

need_economy_stop = "economy_stop_weekly_min_cents" not in before_cols
need_buyin_active = "buyin_enforcement_active" not in before_cols

if not need_economy_stop and not need_buyin_active:
    print("\n  Both target columns already exist -- nothing to do.")
    sys.exit(0)

print(f"\n  economy_stop_weekly_min_cents needs adding : {need_economy_stop}")
print(f"  buyin_enforcement_active needs adding      : {need_buyin_active}")


# ── Step 2: add the columns (additive, single transaction) ───────────────────

print()
print("=" * 60)
print("STEP 2  -- Adding missing column(s)")
print("=" * 60)

try:
    with engine.begin() as conn:
        if need_economy_stop:
            conn.execute(text(
                "ALTER TABLE leagues ADD COLUMN economy_stop_weekly_min_cents INTEGER"
            ))
            print("\n  leagues.economy_stop_weekly_min_cents added (nullable, no default, no backfill)")

        if need_buyin_active:
            # Single-statement NOT NULL DEFAULT add (MIG-1) — Postgres 11+
            # applies this to existing rows atomically as a metadata-only
            # operation, no separate backfill UPDATE needed.
            conn.execute(text(
                "ALTER TABLE leagues ADD COLUMN buyin_enforcement_active "
                "BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            print("  leagues.buyin_enforcement_active added: NOT NULL DEFAULT FALSE, "
                  "backfilled on existing rows atomically")
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
    after_cols = _existing_leagues_columns(conn)
print(f"\n  {sorted(after_cols)}")

missing = {"economy_stop_weekly_min_cents", "buyin_enforcement_active"} - after_cols
if missing:
    print(f"\n!! ERROR: still missing after migration: {sorted(missing)}")
    sys.exit(1)

from db.schema import SessionLocal, League

with SessionLocal() as db:
    n = db.query(League).count()
    print(f"\n  leagues rows: {n}")
    league = db.query(League).first()
    if league:
        _ = league.economy_stop_weekly_min_cents
        _ = league.buyin_enforcement_active
        print(f"  verified via ORM on league #{league.id}: "
              f"economy_stop_weekly_min_cents={league.economy_stop_weekly_min_cents!r}, "
              f"buyin_enforcement_active={league.buyin_enforcement_active!r}")

print("\n  MIGRATION COMPLETE.\n")
