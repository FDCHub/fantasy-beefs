"""
Migration: add refreshed_at column to matchups and backfill existing rows.

Run once against Railway Postgres before the first Tuesday sync:
    DATABASE_URL=<url> python migrations/add_matchup_refreshed_at.py

Idempotency:
  - ADD COLUMN IF NOT EXISTS: safe to re-run; column already present → no-op.
  - UPDATE ... WHERE refreshed_at IS NULL: after the first run, no NULL rows
    remain, so a second run touches zero rows — no-op.

Backfill rationale:
  Production matchups were seeded 2026-06-30 with confirmed real final scores.
  Without the backfill, every seeded row reads NULL refreshed_at after the
  ALTER TABLE, and _assert_slate_fresh(check_refreshed=True) would block
  settlement of any historical or catch-up week with a false "not fresh" alert.
  Backfilling marks them fresh so the self-guard only fires on rows that were
  genuinely never touched by _step_refresh_scores.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from db.schema import engine

with engine.connect() as conn:
    conn.execute(text(
        "ALTER TABLE matchups ADD COLUMN IF NOT EXISTS refreshed_at TIMESTAMP"
    ))
    result = conn.execute(text(
        "UPDATE matchups SET refreshed_at = NOW() WHERE refreshed_at IS NULL"
    ))
    conn.commit()
    print(
        f"OK  matchups.refreshed_at ready — "
        f"{result.rowcount} existing row(s) backfilled as fresh"
    )
