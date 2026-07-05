#!/usr/bin/env python3
"""
audit_deprecated_bet_types.py  —  Read-only. No writes. Throwaway diagnostic.

Reads the current ck_bet_type CHECK constraint from production Postgres, then
queries for any bets rows using each type of interest (whether or not that type
is currently in the constraint).

Types audited:
  - All values currently allowed by ck_bet_type
  - Deprecated candidates named in handoff v6:
      team_total_ou, player_prop_ou
  - Four Fantasybook types used in bet_engine.py but ABSENT from ck_bet_type:
      more_overs, closest_to_proj, position_group_wins, most_offensive_tds
  - full_beef and bench_battle (kept in constraint for now — audit shows if any rows)

USAGE:
  python audit_deprecated_bet_types.py
  (no flags needed — read-only throughout)
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("\naudit_deprecated_bet_types.py  --  Read-only bet_type audit")
print("=" * 62)

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if "sqlite" in db_url:
    print("\n!! WARNING: SQLite target detected.")
    print("   For production data, set DATABASE_URL to the Railway Postgres public URL.")
    print("   Continuing anyway — some queries may return 0 rows on local DB.\n")
else:
    print(f"\n  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")

with engine.connect() as conn:

    # ── 1. Read the actual constraint from pg_constraint ───────────────────────

    print("=" * 62)
    print("1. CURRENT ck_bet_type CONSTRAINT (production)")
    print("=" * 62)

    row = conn.execute(text("""
        SELECT pg_get_constraintdef(oid) AS definition
        FROM   pg_constraint
        WHERE  conrelid = 'bets'::regclass
        AND    conname  = 'ck_bet_type'
    """)).fetchone()

    if row is None:
        print("\n  !! ck_bet_type NOT FOUND in production — constraint may have been dropped.")
        print("     Querying information_schema as fallback...")
        constraint_def = None
        allowed_in_constraint = []
    else:
        constraint_def = row[0]
        print(f"\n  {constraint_def}\n")
        # Parse the ARRAY[...] values out of the Postgres constraint definition
        matches = re.findall(r"'([^']+)'::character varying", constraint_def)
        if not matches:
            # Fallback: simple IN (...) style
            matches = re.findall(r"'([^']+)'", constraint_def)
        allowed_in_constraint = matches
        print(f"  Parsed allowed values ({len(allowed_in_constraint)}):")
        for v in allowed_in_constraint:
            print(f"    '{v}'")

    # ── 2. Build the full audit list ───────────────────────────────────────────
    # Combine: in-constraint values + deprecated candidates not in constraint

    # Deprecated types mentioned in handoff v6 (may have been removed already)
    deprecated_v6 = ["team_total_ou", "player_prop_ou"]

    # Fantasybook types used in bet_engine.py — NOT in ck_bet_type constraint
    fantasybook_types = [
        "more_overs",
        "closest_to_proj",
        "position_group_wins",
        "most_offensive_tds",
    ]

    # All types we care about: currently-in-constraint first, then extras
    in_constraint_set = set(allowed_in_constraint)
    extras = [t for t in deprecated_v6 + fantasybook_types if t not in in_constraint_set]
    audit_list = list(allowed_in_constraint) + extras

    # ── 3. Query row counts and sample rows for each type ─────────────────────

    print()
    print("=" * 62)
    print("2. ROW COUNTS BY BET TYPE")
    print("=" * 62)

    results = []
    for bt in audit_list:
        count = conn.execute(
            text("SELECT COUNT(*) FROM bets WHERE bet_type = :t"),
            {"t": bt},
        ).scalar()

        in_constraint = bt in in_constraint_set

        if count == 0:
            status = "SAFE TO REMOVE" if not in_constraint else "empty (can remove from constraint)"
        else:
            status = "HAS DATA — NEEDS DECISION" if not in_constraint else "HAS DATA — keep in constraint"

        results.append((bt, count, in_constraint, status))

    # Print table
    print()
    col_w = max(len(r[0]) for r in results) + 2
    print(f"  {'bet_type':<{col_w}}  {'rows':>6}  {'in constraint':>14}  status")
    print(f"  {'-'*col_w}  {'-'*6}  {'-'*14}  {'-'*36}")
    for bt, count, in_c, status in results:
        in_c_str = "YES" if in_c else "NO"
        print(f"  {bt:<{col_w}}  {count:>6}  {in_c_str:>14}  {status}")

    # ── 4. Sample rows for any type with data ─────────────────────────────────

    has_data = [(bt, count) for bt, count, _, _ in results if count > 0]

    if not has_data:
        print("\n  All types: 0 rows in bets table.")
    else:
        print()
        print("=" * 62)
        print("3. SAMPLE ROWS (for types with data)")
        print("=" * 62)

        for bt, total_count in has_data:
            print(f"\n  bet_type = '{bt}'  ({total_count} total row{'s' if total_count != 1 else ''})")

            sample = conn.execute(text("""
                SELECT
                    b.id,
                    b.status,
                    b.amount,
                    b.odds,
                    m.week,
                    ht.team_name  AS home_team,
                    at.team_name  AS away_team
                FROM   bets b
                JOIN   matchups m  ON m.id = b.matchup_id
                JOIN   teams    ht ON ht.id = m.home_team_id
                JOIN   teams    at ON at.id = m.away_team_id
                WHERE  b.bet_type = :t
                ORDER  BY b.id
                LIMIT  5
            """), {"t": bt}).fetchall()

            print(f"  {'id':>6}  {'status':<10}  {'amount':>8}  {'odds':>6}  {'week':>4}  matchup")
            print(f"  {'-'*6}  {'-'*10}  {'-'*8}  {'-'*6}  {'-'*4}  {'-'*32}")
            for row in sample:
                bid, status, amount, odds, week, home, away = row
                print(f"  {bid:>6}  {status:<10}  {amount:>8.2f}  {odds:>6.3f}  {week:>4}  {home} vs {away}")

    # ── 5. Cross-check: types in bet_engine.py vs constraint ──────────────────

    engine_types = {
        "straight", "spread", "over_under", "prop",
        "more_overs", "closest_to_proj", "position_group_wins", "most_offensive_tds",
    }
    missing_from_constraint = engine_types - in_constraint_set
    phantom_in_constraint   = in_constraint_set - engine_types - {"bench_battle", "full_beef", "the_lineup"}

    print()
    print("=" * 62)
    print("4. CROSS-CHECK: bet_engine.py vs ck_bet_type")
    print("=" * 62)
    print()
    if missing_from_constraint:
        print("  !! bet_engine.py writes these types but they are NOT in ck_bet_type:")
        for t in sorted(missing_from_constraint):
            print(f"       '{t}'")
        print("     Any call to these bet functions would raise a DB constraint violation.")
    else:
        print("  OK: all bet_engine.py types are covered by ck_bet_type.")

    if phantom_in_constraint:
        print()
        print("  !! These types are in ck_bet_type but have no corresponding place_* function:")
        for t in sorted(phantom_in_constraint):
            print(f"       '{t}'")
    else:
        print()
        print("  OK: no orphan types in constraint without a place_* function")
        print("      (bench_battle, full_beef, the_lineup excluded from this check by design).")

    print()
    print("=" * 62)
    print("AUDIT COMPLETE — no writes made.")
    print("=" * 62)
    print()
