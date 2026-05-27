"""
Migration: Commissioner Rules Engine — creates 5 new tables.

Safe to re-run: create_all is additive; existing tables are untouched.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Base, SessionLocal, engine

_NEW_TABLES = [
    "commissioner_rules",
    "escrow_accounts",
    "escrow_transactions",
    "rule_executions",
    "rule_audit_log",
]


def run_migration() -> None:
    Base.metadata.create_all(engine)
    print(f"  + tables ensured: {', '.join(_NEW_TABLES)}")

    with SessionLocal() as db:
        from db.schema import (
            CommissionerRule,
            EscrowAccount,
            EscrowTransaction,
            RuleExecution,
            RuleAuditLog,
        )
        print()
        print("  Table row counts after migration:")
        for cls in (CommissionerRule, EscrowAccount, EscrowTransaction, RuleExecution, RuleAuditLog):
            n = db.query(cls).count()
            print(f"    {cls.__tablename__:<26} {n} rows")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: Commissioner Rules Engine...")
    run_migration()
    print("\nDone.")
