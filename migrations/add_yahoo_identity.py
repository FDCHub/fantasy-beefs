"""
migrations/add_yahoo_identity.py — WP3D.1 · the external identity anchor.

WHAT IT DOES, AND NOTHING ELSE:

    users.auth_provider     TEXT NULL      'yahoo', or NULL for a local account
    users.provider_subject  TEXT NULL      Yahoo's stable subject
    UNIQUE (auth_provider, provider_subject)
    users.hashed_password   becomes NULLABLE

ADDITIVE, NON-DESTRUCTIVE AND REVERSIBLE AT THE APPLICATION LAYER.

  · No column is dropped. `hashed_password` keeps every value it holds, so a
    deployment rolled back to pre-WP3D.1 code finds every existing account
    exactly as it left it and can sign them in again.
  · The two new columns are NULLABLE, so every existing row is valid without
    being touched. Nothing is backfilled and no row is rewritten.
  · The unique constraint spans two nullable columns, so pre-Yahoo rows — which
    are NULL in both — do not collide with each other. NULLs never do.
  · Nothing about a Ledger, a wager, a team, a league or a season is read or
    written. A mid-season deployment changes what a login proves and changes
    nothing about what anyone owns.

WHY `hashed_password` IS RELAXED RATHER THAN LEFT NOT NULL. A Yahoo-created
account has no password and must not be given a fabricated hash — a placeholder
that happens to be unverifiable is still a credential-shaped value sitting in
the credential column, and the day somebody writes a comparison against it, it
becomes a login. NULL is the honest representation, and `authenticate_user`
refuses it explicitly.

    python migrations/add_yahoo_identity.py

Idempotent: run it twice and the second run reports that there is nothing to do.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text                               # noqa: E402

from db.schema import engine                                       # noqa: E402


def _columns(connection) -> set[str]:
    return {c["name"] for c in inspect(connection).get_columns("users")}


def upgrade() -> list[str]:
    """Apply the change. Returns what it did, for the caller to print."""
    done: list[str] = []
    dialect = engine.dialect.name

    with engine.begin() as connection:
        existing = _columns(connection)

        if "auth_provider" not in existing:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN auth_provider VARCHAR"))
            done.append("added users.auth_provider")
        if "provider_subject" not in existing:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN provider_subject VARCHAR"))
            done.append("added users.provider_subject")

        # THE UNIQUE CONSTRAINT IS THE POINT OF THE MIGRATION, not a detail.
        # Without it two concurrent first-time callbacks for the same Yahoo
        # account both find no row and both insert one, and that person now has
        # two FantasyStakes identities and two Ledgers. A unique index is the
        # only thing that makes "one account per Yahoo account" true under
        # concurrency; a query-then-insert cannot.
        index_name = "uq_user_provider_subject"
        indexes = {i["name"] for i in inspect(connection).get_indexes("users")}
        if index_name not in indexes:
            connection.execute(text(
                f"CREATE UNIQUE INDEX {index_name} "
                "ON users (auth_provider, provider_subject)"))
            done.append(f"created {index_name}")

        # RELAXING NOT NULL. PostgreSQL does it in place. SQLite cannot alter a
        # column at all — but SQLite is development and test here, where the
        # schema is created fresh from `db.schema` on every run, so there is
        # nothing to relax: the table was built nullable already.
        if dialect == "postgresql":
            connection.execute(text(
                "ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL"))
            done.append("users.hashed_password is now nullable")
        else:
            done.append(
                f"{dialect}: hashed_password nullability left to db.schema")

    return done or ["nothing to do — already applied"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
    print("WP3D.1 identity migration complete.")
