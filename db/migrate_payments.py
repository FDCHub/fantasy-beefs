"""
Migration: payments — creates treasury / buy-in / payout / audit tables
and adds buy_in_paid + stripe_account_id columns to users.

Safe to re-run:
  • create_all is additive for new tables.
  • ALTER TABLE ADD COLUMN is wrapped in a try/except for idempotency.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from db.schema import Base, SessionLocal, engine


_NEW_TABLES = [
    "league_treasury",
    "buy_in_records",
    "payout_records",
    "stripe_audit_log",
]

_ALTER_USERS = [
    "ALTER TABLE users ADD COLUMN buy_in_paid       INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN stripe_account_id TEXT",
]


def run_migration() -> None:
    # ── New tables (additive) ─────────────────────────────────────────────────
    Base.metadata.create_all(engine)
    print(f"  + tables ensured: {', '.join(_NEW_TABLES)}")

    # ── New columns on existing users table ───────────────────────────────────
    with engine.connect() as conn:
        for stmt in _ALTER_USERS:
            col = stmt.split("ADD COLUMN")[1].strip().split()[0]
            try:
                conn.execute(text(stmt))
                conn.commit()
                print(f"  + users.{col} added")
            except Exception:
                print(f"  . users.{col} already exists — skipped")

    # ── Verify ────────────────────────────────────────────────────────────────
    with SessionLocal() as db:
        from db.schema import LeagueTreasury, BuyInRecord, PayoutRecord, StripeAuditLog, User
        print()
        print("  Table row counts after migration:")
        for cls in (LeagueTreasury, BuyInRecord, PayoutRecord, StripeAuditLog):
            n = db.query(cls).count()
            print(f"    {cls.__tablename__:<22} {n} rows")

        # Confirm new columns exist by querying one user
        user = db.query(User).first()
        if user:
            _ = user.buy_in_paid, user.stripe_account_id
            print(f"\n  users.buy_in_paid / stripe_account_id verified on user #{user.id}")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: payments...")
    run_migration()
    print("\nDone.")
