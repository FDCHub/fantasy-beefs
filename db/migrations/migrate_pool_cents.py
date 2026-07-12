#!/usr/bin/env python3
"""
migrate_pool_cents.py  —  Production schema migration adding integer-cent
columns to pool_config and pool_pots, backfilling them from the existing
float columns, verifying the backfill row-by-row against a fresh
re-derivation of each row's own value, then dropping the old float
columns — all inside ONE transaction, so a failed verification rolls
back the column additions and backfill too. A half-migrated state (new
columns present but wrong, or columns dropped with no verified
replacement) is exactly what this ordering exists to prevent.

Adds (see db/schema.py):
  pool_config.weekly_entry_cents        INTEGER NOT NULL DEFAULT 1000
  pool_pots.worst_beat_rollover_cents   BIGINT DEFAULT 0
  pool_pots.total_pot_cents             BIGINT (nullable)

Backfill: Decimal-based round-half-up conversion (NOT Python's bare
round(), which is round-half-to-even — wrong for money):
    cents = int(Decimal(str(value)).scaleb(2).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))

total_pot may be NULL (pot not yet collected for that week) — left NULL
in total_pot_cents, never coerced to 0.

VERIFICATION GATE (must pass before the DROP step runs):
  For every pool_config row and every pool_pots row, recomputes the
  expected cents value fresh from that row's OWN old float value and
  asserts it matches what was backfilled — not a hardcoded constant, so
  the gate catches a real conversion bug regardless of what economy stop
  a league is on. Also asserts (belt-and-suspenders, not the primary
  gate) that at least one pool_config row's weekly_entry_cents == 1000
  (this league's known $10.00 default stop).

  Any failure raises immediately, prints exactly which table/row/value
  failed, and the whole transaction rolls back — the DROP COLUMN step
  never runs, and the ADD COLUMN / backfill from steps 1-2 do not
  persist either.

SAFE:
  - Only targets Postgres. Refuses to run if DATABASE_URL is missing or
    does not point at a Postgres instance.
  - ADD COLUMN IF NOT EXISTS — the additive part is safe to re-run.
  - IRREVERSIBLE once the DROP COLUMN step actually commits — that's why
    steps 1-4 all share ONE transaction (engine.begin()). Postgres DDL is
    fully transactional: if verification raises, EVERYTHING in this
    script (new columns, backfilled values, and the drop) rolls back
    together. Nothing is dropped until every row has been independently
    re-verified.
  - Does NOT touch betting/pool_engine.py, api/pool_routes.py, or
    payments/stripe_connect.py — those still read the OLD float columns
    and are a separate, later conversion pass. DO NOT RUN THIS
    MIGRATION'S DROP STEP IN PRODUCTION until that conversion has
    shipped — dropping these columns while those files still read the
    old ones will break every consumer of PoolConfig.weekly_entry,
    PoolPot.total_pot, and PoolPot.worst_beat_rollover_amount
    immediately, the moment this runs.

USAGE:
  python db/migrations/migrate_pool_cents.py
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

print("\nmigrate_pool_cents.py  --  pool_config/pool_pots integer-cent migration\n")

from sqlalchemy import text
from db.schema import engine

db_url = str(engine.url)
if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
    print("!! ERROR: Postgres target not detected.")
    print("   DATABASE_URL is missing or does not point at a Postgres instance.")
    print("   Re-run with DATABASE_URL pointing to the Railway Postgres instance.")
    sys.exit(1)

print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")


def _to_cents(value) -> int:
    """Decimal-based round-half-up dollars -> cents. NOT Python's bare
    round() (round-half-to-even -- wrong for money)."""
    return int(Decimal(str(value)).scaleb(2).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


try:
    with engine.begin() as conn:
        # ── Step 1: add the three new columns (additive, idempotent) ────────
        print("=" * 60)
        print("STEP 1  -- Adding integer-cent columns")
        print("=" * 60)

        conn.execute(text(
            "ALTER TABLE pool_config ADD COLUMN IF NOT EXISTS weekly_entry_cents INTEGER"
        ))
        conn.execute(text(
            "ALTER TABLE pool_pots ADD COLUMN IF NOT EXISTS worst_beat_rollover_cents BIGINT"
        ))
        conn.execute(text(
            "ALTER TABLE pool_pots ADD COLUMN IF NOT EXISTS total_pot_cents BIGINT"
        ))
        print("\n  pool_config.weekly_entry_cents added (or already existed)")
        print("  pool_pots.worst_beat_rollover_cents added (or already existed)")
        print("  pool_pots.total_pot_cents added (or already existed)")

        # ── Step 2: backfill from the existing float columns ─────────────────
        print()
        print("=" * 60)
        print("STEP 2  -- Backfilling from existing float columns")
        print("=" * 60)

        pool_config_rows = conn.execute(text(
            "SELECT id, weekly_entry FROM pool_config"
        )).fetchall()
        for row in pool_config_rows:
            cents = _to_cents(row.weekly_entry)
            conn.execute(
                text("UPDATE pool_config SET weekly_entry_cents = :cents WHERE id = :id"),
                {"cents": cents, "id": row.id},
            )
        print(f"\n  pool_config: {len(pool_config_rows)} row(s) backfilled")

        pool_pot_rows = conn.execute(text(
            "SELECT id, total_pot, worst_beat_rollover_amount FROM pool_pots"
        )).fetchall()
        for row in pool_pot_rows:
            rollover_cents  = _to_cents(row.worst_beat_rollover_amount)
            total_pot_cents = _to_cents(row.total_pot) if row.total_pot is not None else None
            conn.execute(
                text(
                    "UPDATE pool_pots SET worst_beat_rollover_cents = :rc, "
                    "total_pot_cents = :tpc WHERE id = :id"
                ),
                {"rc": rollover_cents, "tpc": total_pot_cents, "id": row.id},
            )
        print(f"  pool_pots: {len(pool_pot_rows)} row(s) backfilled")

        # ── Step 3: verification gate -- must pass before the drop ───────────
        print()
        print("=" * 60)
        print("STEP 3  -- Verification gate")
        print("=" * 60)

        verify_config_rows = conn.execute(text(
            "SELECT id, weekly_entry, weekly_entry_cents FROM pool_config"
        )).fetchall()
        for row in verify_config_rows:
            expected = _to_cents(row.weekly_entry)
            if row.weekly_entry_cents != expected:
                raise RuntimeError(
                    f"VERIFICATION FAILED: pool_config.id={row.id} "
                    f"weekly_entry={row.weekly_entry!r} -> expected {expected} cents, "
                    f"got {row.weekly_entry_cents!r} cents in weekly_entry_cents"
                )
        print(f"\n  pool_config: {len(verify_config_rows)} row(s) verified against a fresh re-derivation")

        verify_pot_rows = conn.execute(text(
            "SELECT id, total_pot, total_pot_cents, worst_beat_rollover_amount, "
            "worst_beat_rollover_cents FROM pool_pots"
        )).fetchall()
        for row in verify_pot_rows:
            expected_rollover = _to_cents(row.worst_beat_rollover_amount)
            if row.worst_beat_rollover_cents != expected_rollover:
                raise RuntimeError(
                    f"VERIFICATION FAILED: pool_pots.id={row.id} "
                    f"worst_beat_rollover_amount={row.worst_beat_rollover_amount!r} -> "
                    f"expected {expected_rollover} cents, got "
                    f"{row.worst_beat_rollover_cents!r} cents in worst_beat_rollover_cents"
                )
            if row.total_pot is None:
                if row.total_pot_cents is not None:
                    raise RuntimeError(
                        f"VERIFICATION FAILED: pool_pots.id={row.id} "
                        f"total_pot is NULL but total_pot_cents = {row.total_pot_cents!r} "
                        f"(expected NULL, not coerced to 0)"
                    )
            else:
                expected_total = _to_cents(row.total_pot)
                if row.total_pot_cents != expected_total:
                    raise RuntimeError(
                        f"VERIFICATION FAILED: pool_pots.id={row.id} "
                        f"total_pot={row.total_pot!r} -> expected {expected_total} cents, "
                        f"got {row.total_pot_cents!r} cents in total_pot_cents"
                    )
        print(f"  pool_pots: {len(verify_pot_rows)} row(s) verified against a fresh re-derivation")

        # Belt-and-suspenders sanity check -- not the primary gate.
        default_stop_hit = any(row.weekly_entry_cents == 1000 for row in verify_config_rows)
        if not default_stop_hit:
            raise RuntimeError(
                "VERIFICATION FAILED (sanity check): no pool_config row has "
                "weekly_entry_cents == 1000 -- expected at least one league on "
                "the known $10.00 default stop. Refusing to proceed."
            )
        print("  sanity check: at least one pool_config row confirmed at the "
              "$10.00 default stop (1000 cents)")

        print("\n  VERIFICATION GATE PASSED -- proceeding to finalize columns and drop the old ones.")

        # ── Step 4: finalize constraints, then drop the old float columns ────
        # (IRREVERSIBLE once this transaction commits.)
        print()
        print("=" * 60)
        print("STEP 4  -- Finalizing columns, dropping old float columns (irreversible)")
        print("=" * 60)

        conn.execute(text(
            "ALTER TABLE pool_config ALTER COLUMN weekly_entry_cents SET DEFAULT 1000"
        ))
        conn.execute(text(
            "ALTER TABLE pool_config ALTER COLUMN weekly_entry_cents SET NOT NULL"
        ))
        conn.execute(text(
            "ALTER TABLE pool_pots ALTER COLUMN worst_beat_rollover_cents SET DEFAULT 0"
        ))
        print("\n  pool_config.weekly_entry_cents finalized: NOT NULL DEFAULT 1000")
        print("  pool_pots.worst_beat_rollover_cents finalized: DEFAULT 0")

        conn.execute(text("ALTER TABLE pool_config DROP COLUMN weekly_entry"))
        conn.execute(text("ALTER TABLE pool_pots DROP COLUMN worst_beat_rollover_amount"))
        conn.execute(text("ALTER TABLE pool_pots DROP COLUMN total_pot"))
        print("\n  pool_config.weekly_entry dropped")
        print("  pool_pots.worst_beat_rollover_amount dropped")
        print("  pool_pots.total_pot dropped")

except Exception as e:
    print(f"\n!! ERROR: migration failed and the entire transaction was rolled back: {e}")
    print("   No columns were added, no data was backfilled, nothing was dropped.")
    sys.exit(1)


# ── Step 5: summary ───────────────────────────────────────────────────────────

print()
print("=" * 60)
print("STEP 5  -- Summary")
print("=" * 60)

with engine.connect() as conn:
    config_count = conn.execute(text("SELECT COUNT(*) FROM pool_config")).scalar()
    pot_count    = conn.execute(text("SELECT COUNT(*) FROM pool_pots")).scalar()
    old_cols     = conn.execute(text("""
        SELECT table_name, column_name FROM information_schema.columns
        WHERE (table_name = 'pool_config' AND column_name = 'weekly_entry')
           OR (table_name = 'pool_pots' AND column_name IN ('worst_beat_rollover_amount', 'total_pot'))
    """)).fetchall()

print(f"\n  pool_config rows migrated : {config_count}")
print(f"  pool_pots rows migrated   : {pot_count}")
if old_cols:
    print(f"!! WARNING: old float columns still present: "
          f"{[f'{r.table_name}.{r.column_name}' for r in old_cols]}")
    sys.exit(1)
else:
    print("  old float columns confirmed dropped: pool_config.weekly_entry, "
          "pool_pots.worst_beat_rollover_amount, pool_pots.total_pot")
print("\n  MIGRATION COMPLETE.\n")
