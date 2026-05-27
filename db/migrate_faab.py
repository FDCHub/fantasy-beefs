"""
Migration: FAAB wallet — creates faab_config, faab_wallets, faab_transactions tables.

Safe to re-run: create_all is additive; existing tables are untouched.
No schema changes to existing tables.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Base, SessionLocal, engine


_NEW_TABLES = ["faab_config", "faab_wallets", "faab_transactions"]


def run_migration() -> None:
    Base.metadata.create_all(engine)
    print(f"  + tables ensured: {', '.join(_NEW_TABLES)}")

    with SessionLocal() as db:
        from db.schema import FaabConfig, FaabWallet, FaabTransaction
        print()
        print("  Table row counts after migration:")
        for cls in (FaabConfig, FaabWallet, FaabTransaction):
            n = db.query(cls).count()
            print(f"    {cls.__tablename__:<22} {n} rows")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: FAAB wallet...")
    run_migration()
    print("\nDone.")
