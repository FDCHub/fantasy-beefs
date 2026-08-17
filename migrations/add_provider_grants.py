"""
migrations/add_provider_grants.py — YAHOO-LIVE-1 · the per-user Yahoo grant.

WHAT IT DOES, AND NOTHING ELSE:

    CREATE TABLE provider_grants        one OAuth grant per (user, provider)
    UNIQUE (user_id, provider)
    leagues.provider_credential_user_id     INTEGER NULL   whose grant syncs it
    leagues.provider_credential_assigned_at TIMESTAMP NULL when that was set

ADDITIVE, NON-DESTRUCTIVE AND REVERSIBLE AT THE APPLICATION LAYER.

  · Nothing is dropped, renamed or rewritten. No existing column changes type
    or nullability, and no existing row is read or updated.
  · The new table is new. A deployment rolled back to pre-YAHOO-LIVE-1 code
    simply never queries it; the rows sit there, harmless, and are still correct
    if the code rolls forward again.
  · `leagues.provider_credential_user_id` is NULLABLE with no default, so every
    existing league is valid unchanged. NULL means "no user has authorized Yahoo
    for this league", which is the truth for every league that exists at the
    moment this runs.
  · No Ledger, wager, team, season or economic value is touched.

WHAT IS NOT STORED HERE. Yahoo Fantasy Information. This table holds OAuth
credentials — the keys used to make a request — and no roster, player, stat,
matchup, standing or league setting. See `auth/provider_grant.py` for the
boundary stated in full.

THE TOKEN COLUMNS HOLD CIPHERTEXT, NOT TOKENS. `access_token_sealed` and
`refresh_token_sealed` are AES-256-GCM envelopes produced by
`auth/token_crypto.py`, each bound to its own row. A deployment with no
`FS_TOKEN_ENCRYPTION_KEY` cannot write them at all — the application refuses
rather than falling back to readable values — so this migration creating the
columns does not create a way to store a plaintext credential.

    python migrations/add_provider_grants.py

Idempotent: run it twice and the second run reports there is nothing to do.

POSTGRESQL IS THE TARGET. SQLite is supported so the development and test
databases match, but SQLite builds this schema from `db.schema` on every run and
therefore proves nothing about PostgreSQL's ALTER behaviour — the PostgreSQL
execution is a separate, explicit certification.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text                               # noqa: E402

from db.schema import engine                                       # noqa: E402

#: Kept beside the DDL rather than imported, so the migration is readable as a
#: single artifact and does not change meaning when the model changes.
TABLE = "provider_grants"

_CREATE_POSTGRES = f"""
CREATE TABLE {TABLE} (
    id                   SERIAL PRIMARY KEY,
    user_id              INTEGER NOT NULL REFERENCES users (id),
    provider             VARCHAR NOT NULL,
    provider_subject     VARCHAR NOT NULL,
    access_token_sealed  TEXT,
    refresh_token_sealed TEXT,
    expires_at           TIMESTAMP,
    granted_scope        VARCHAR,
    status               VARCHAR NOT NULL DEFAULT 'active',
    token_version        INTEGER NOT NULL DEFAULT 1,
    created_at           TIMESTAMP,
    updated_at           TIMESTAMP,
    last_refresh_at      TIMESTAMP,
    last_error_code      VARCHAR,
    last_error_at        TIMESTAMP,
    CONSTRAINT uq_provider_grant_user UNIQUE (user_id, provider),
    CONSTRAINT ck_provider_grant_status
        CHECK (status IN ('active','reconnect_required','disconnected'))
)
"""

_CREATE_SQLITE = f"""
CREATE TABLE {TABLE} (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id              INTEGER NOT NULL REFERENCES users (id),
    provider             VARCHAR NOT NULL,
    provider_subject     VARCHAR NOT NULL,
    access_token_sealed  TEXT,
    refresh_token_sealed TEXT,
    expires_at           TIMESTAMP,
    granted_scope        VARCHAR,
    status               VARCHAR NOT NULL DEFAULT 'active',
    token_version        INTEGER NOT NULL DEFAULT 1,
    created_at           TIMESTAMP,
    updated_at           TIMESTAMP,
    last_refresh_at      TIMESTAMP,
    last_error_code      VARCHAR,
    last_error_at        TIMESTAMP,
    CONSTRAINT uq_provider_grant_user UNIQUE (user_id, provider),
    CONSTRAINT ck_provider_grant_status
        CHECK (status IN ('active','reconnect_required','disconnected'))
)
"""


def upgrade() -> list[str]:
    """Apply the change. Returns what it did, for the caller to print."""
    done: list[str] = []
    dialect = engine.dialect.name

    with engine.begin() as connection:
        inspector = inspect(connection)

        if TABLE in inspector.get_table_names():
            done.append(f"{TABLE} already exists")
        else:
            ddl = _CREATE_POSTGRES if dialect == "postgresql" else _CREATE_SQLITE
            connection.execute(text(ddl))
            done.append(f"created {TABLE}")
            # THE INDEX IS SEPARATE FROM THE UNIQUE CONSTRAINT and serves a
            # different query: "this user's grants" is the lookup every request
            # makes, and the unique constraint's index leads with user_id only
            # incidentally. Naming it explicitly means it exists on both engines.
            connection.execute(text(
                f"CREATE INDEX ix_{TABLE}_user_id ON {TABLE} (user_id)"))
            done.append(f"created ix_{TABLE}_user_id")

        league_columns = {c["name"] for c in inspect(connection)
                          .get_columns("leagues")}
        if "provider_credential_user_id" not in league_columns:
            # NO FOREIGN KEY ON SQLITE'S ALTER PATH. SQLite cannot add a column
            # with a REFERENCES clause to an existing table without rebuilding
            # it, and rebuilding a live table to gain a constraint the
            # development database does not enforce anyway would be trading a
            # real risk for a nominal gain. PostgreSQL — the production target —
            # gets the constraint.
            if dialect == "postgresql":
                connection.execute(text(
                    "ALTER TABLE leagues ADD COLUMN provider_credential_user_id "
                    "INTEGER REFERENCES users (id)"))
            else:
                connection.execute(text(
                    "ALTER TABLE leagues ADD COLUMN provider_credential_user_id "
                    "INTEGER"))
            done.append("added leagues.provider_credential_user_id")

        if "provider_credential_assigned_at" not in league_columns:
            # PLAIN TIMESTAMP, NO DEFAULT. Backfilling `now()` onto existing
            # leagues would assert that somebody assigned a credential owner at
            # migration time, which nobody did. NULL is the honest value and it
            # reads as "never assigned", which is exactly true.
            connection.execute(text(
                "ALTER TABLE leagues ADD COLUMN "
                "provider_credential_assigned_at TIMESTAMP"))
            done.append("added leagues.provider_credential_assigned_at")

    return done or ["nothing to do — already applied"]


if __name__ == "__main__":
    for line in upgrade():
        print(f"  · {line}")
    print("YAHOO-LIVE-1 provider-grant migration complete.")
