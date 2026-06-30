#!/usr/bin/env python3
"""
fix_yahoo_projection_columns.py  —  ONE-OFF MIGRATION (do not re-run)

Background: seed_yahoo_projections.py backfilled 2,407 Projection rows with
source='yahoo', season=2025. Yahoo's API does not retain historical projections
— querying a completed week returns the final actual fantasy points, not the
pre-week projection. Those actual-points values were written into projected_points
while actual_points stayed at the hardcoded 0.0 placeholder.

This migration corrects that:
  - Moves projected_points → actual_points  (the real final score)
  - Sets projected_points = NULL            (honest: we have no Yahoo projection)
  - Also drops the NOT NULL constraint on both columns (schema now allows NULL)

Only touches source='yahoo' AND season=2025 rows.
Leaves source='fantasypros' rows untouched.

USAGE:
  python fix_yahoo_projection_columns.py              # dry-run: prints plan
  python fix_yahoo_projection_columns.py --confirm    # live write
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONFIRM = "--confirm" in sys.argv

print("\nfix_yahoo_projection_columns.py — one-off column-swap migration")
print(f"  mode: {'LIVE WRITE' if CONFIRM else 'DRY-RUN (pass --confirm to apply)'}\n")

from sqlalchemy import text
from db.schema import SessionLocal, engine

# ── Step 1: read current state ────────────────────────────────────────────────

with SessionLocal() as s:
    total_yahoo = s.execute(
        text("SELECT COUNT(*) FROM projections WHERE source='yahoo' AND season=2025")
    ).scalar()

    already_fixed = s.execute(
        text(
            "SELECT COUNT(*) FROM projections "
            "WHERE source='yahoo' AND season=2025 AND projected_points IS NULL"
        )
    ).scalar()

    sample_rows = s.execute(
        text(
            "SELECT id, player_id, week, projected_points, actual_points "
            "FROM projections "
            "WHERE source='yahoo' AND season=2025 AND projected_points IS NOT NULL "
            "ORDER BY id "
            "LIMIT 3"
        )
    ).fetchall()

print(f"  source='yahoo' season=2025 rows : {total_yahoo}")
print(f"  already migrated (proj IS NULL) : {already_fixed}")
print(f"  rows needing migration          : {total_yahoo - already_fixed}")
print()

if sample_rows:
    print("  Sample rows (before migration):")
    print(f"  {'id':>6}  {'player_id':>9}  {'week':>4}  {'projected_pts':>13}  {'actual_pts':>10}")
    print(f"  {'-'*6}  {'-'*9}  {'-'*4}  {'-'*13}  {'-'*10}")
    for row in sample_rows:
        print(f"  {row[0]:>6}  {row[1]:>9}  {row[2]:>4}  {row[3]:>13}  {row[4]:>10}")
    print()

if total_yahoo - already_fixed == 0:
    print("  Nothing to do — all rows already migrated.")
    sys.exit(0)

if not CONFIRM:
    print("  DRY-RUN — no changes made.")
    print("  Re-run with --confirm to apply.\n")
    sys.exit(0)

# ── Step 2: drop NOT NULL constraints, then swap columns ──────────────────────
# Must drop NOT NULL on projected_points before setting it to NULL.
# SQLite does not support ALTER COLUMN — use raw SQL that works on Postgres.

db_url = str(engine.url)
if "sqlite" in db_url:
    print("!! ERROR: SQLite does not support ALTER COLUMN DROP NOT NULL.")
    print("   Run this against the production Postgres instance via DATABASE_URL.")
    sys.exit(1)

print("  Applying migration ...")

with engine.begin() as conn:
    # Drop NOT NULL constraints (idempotent if already dropped)
    conn.execute(text(
        "ALTER TABLE projections ALTER COLUMN projected_points DROP NOT NULL"
    ))
    conn.execute(text(
        "ALTER TABLE projections ALTER COLUMN actual_points DROP NOT NULL"
    ))

    # Swap: move projected_points → actual_points, set projected_points = NULL
    result = conn.execute(text(
        "UPDATE projections "
        "SET actual_points = projected_points, projected_points = NULL "
        "WHERE source = 'yahoo' AND season = 2025 AND projected_points IS NOT NULL"
    ))
    rows_updated = result.rowcount

print(f"  Rows updated: {rows_updated}")
print()

# ── Step 3: verify ────────────────────────────────────────────────────────────

with SessionLocal() as s:
    after_sample = s.execute(
        text(
            "SELECT id, player_id, week, projected_points, actual_points "
            "FROM projections "
            "WHERE source='yahoo' AND season=2025 "
            "ORDER BY id "
            "LIMIT 3"
        )
    ).fetchall()

    null_proj = s.execute(
        text(
            "SELECT COUNT(*) FROM projections "
            "WHERE source='yahoo' AND season=2025 AND projected_points IS NULL"
        )
    ).scalar()

    non_null_proj = s.execute(
        text(
            "SELECT COUNT(*) FROM projections "
            "WHERE source='yahoo' AND season=2025 AND projected_points IS NOT NULL"
        )
    ).scalar()

    fp_unchanged = s.execute(
        text(
            "SELECT COUNT(*) FROM projections "
            "WHERE source='fantasypros'"
        )
    ).scalar()

print("  After migration:")
print(f"  {'id':>6}  {'player_id':>9}  {'week':>4}  {'projected_pts':>13}  {'actual_pts':>10}")
print(f"  {'-'*6}  {'-'*9}  {'-'*4}  {'-'*13}  {'-'*10}")
for row in after_sample:
    proj = str(row[3]) if row[3] is not None else "NULL"
    act  = str(row[4]) if row[4] is not None else "NULL"
    print(f"  {row[0]:>6}  {row[1]:>9}  {row[2]:>4}  {proj:>13}  {act:>10}")

print()
print(f"  projected_points IS NULL  : {null_proj}  (should equal {rows_updated})")
print(f"  projected_points NOT NULL : {non_null_proj}  (should be 0)")
print(f"  source='fantasypros' rows : {fp_unchanged}  (should be unchanged)")
print()

all_ok = (null_proj == rows_updated and non_null_proj == 0)
print(f"  {'MIGRATION COMPLETE — all checks passed.' if all_ok else '!! ONE OR MORE CHECKS FAILED — review output above'}")
print()
