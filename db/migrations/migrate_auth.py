"""
Migration: auth — creates the users table and seeds one account per team.

Safe to re-run: create_all is additive; seed_users skips existing emails.

Commissioner account: team-1 owner  (kevin.mahoney@gmail.com)
Default password for ALL seeded accounts: beefs2024
Change passwords before real deployment.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from db.schema import Base, SessionLocal, User, engine
from auth.jwt_auth import SEED_PASSWORD, seed_users


def run_migration() -> None:
    # Create users table (no-op if it already exists)
    Base.metadata.create_all(engine)
    print("  + users table ensured")

    with SessionLocal() as db:
        before = db.query(User).count()
        created = seed_users(db)
        after   = db.query(User).count()

        if created:
            print(f"  + {len(created)} user(s) seeded  (password: '{SEED_PASSWORD}')")
        else:
            print(f"  . {before} user(s) already exist — skipped seeding")

        # Print roster
        users = db.query(User).order_by(User.id).all()
        print()
        print("  Seeded accounts:")
        for u in users:
            print(f"    [{u.role:<12}]  {u.email}")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print("Running migration: auth...")
    run_migration()
    print("\nDone.")
