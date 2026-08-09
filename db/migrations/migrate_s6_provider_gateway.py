#!/usr/bin/env python3
"""
migrate_s6_provider_gateway.py — Sprint 6 provider identity and conflict schema.

Five groups of change, all additive except two DROPPED constraints that S6-R1
requires be dropped:

  1. PROVIDER IDENTITY COLUMNS on leagues, teams, players and matchups, each
     with a scoped UNIQUE. Nullable throughout: every Sprint 1-5 row keeps NULL
     and is simply "no provider identity", which the resolver fails closed on
     rather than treating as a wildcard.

  2. teams.email UNIQUE -> DROPPED, replaced by a plain index. Under S6-R1 an
     email is not identity, and the global UNIQUE additionally made it
     impossible for one manager to hold a team in two leagues. The COLUMN and
     its data are untouched; only the constraint goes.

  3. players.name UNIQUE -> DROPPED, replaced by a plain index (recon R-4). Two
     real NFL players may share a name, and identity-safe ingestion must not
     fail on a name collision.

  4. players.yahoo_id UNIQUE -> DROPPED, replaced by a plain index (recon R-5).
     The column holds the BARE Yahoo player_id with no game segment, so the same
     integer denotes different players in different seasons; a global UNIQUE on
     it is a cross-season collision. Authoritative identity moves to
     players.provider_player_key, which carries the game segment.

  5. provider_conflict table (S6-R3, §10), plus the mirrored-pair unique index
     on matchups (§5).

NO BACKFILL OF PROVIDER KEYS. This migration deliberately writes no
provider_team_key, even though db/team_resolver.py can currently parse a Yahoo
team ordinal out of teams.email. Deriving authoritative identity from the email
smuggle is exactly the practice S6-R1 abolishes, and a backfill would launder it
into the new column. Provider keys are written only by an actual provider
ingest, which is where the provider states them.

NO FINALITY IS INVENTED. Nothing here touches matchups.finalized_at.

PRE-FLIGHT REFUSALS. Dropping a UNIQUE is safe; ADDING one is not, so the three
new UNIQUEs are verified against live data first and the migration aborts, whole,
if any existing rows would violate them.

Postgres-only, idempotent, one transaction — the existing migration convention.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

_CREATE_PROVIDER_CONFLICT = """
    CREATE TABLE provider_conflict (
        id                 SERIAL PRIMARY KEY,
        league_id          INTEGER NOT NULL REFERENCES leagues(id),
        provider           VARCHAR NOT NULL,
        external_identity  VARCHAR NOT NULL,
        conflict_type      VARCHAR NOT NULL,
        existing_value     TEXT    NOT NULL,
        provider_value     TEXT    NOT NULL,
        contradicted_field VARCHAR NOT NULL,
        conflict_key       VARCHAR NOT NULL,
        detected_at        TIMESTAMPTZ NOT NULL,
        last_seen_at       TIMESTAMPTZ NOT NULL,
        occurrence_count   INTEGER NOT NULL DEFAULT 1,
        resolved_at        TIMESTAMPTZ,
        resolved_by        VARCHAR,
        resolution_note    TEXT,
        audit_metadata     JSON,
        CONSTRAINT uq_provider_conflict_key UNIQUE (conflict_key),
        CONSTRAINT ck_provider_conflict_type CHECK (
            conflict_type IN ('POST_FINAL_SCORE','POST_FINAL_WINNER',
                              'POST_FINAL_FINALITY_RETRACTION',
                              'FROZEN_SEASON_BOUNDARY','IDENTITY_CONFLICT')),
        CONSTRAINT ck_provider_conflict_resolution_pair CHECK (
            (resolved_at IS NOT NULL) = (resolved_by IS NOT NULL)),
        CONSTRAINT ck_provider_conflict_occurrences CHECK (occurrence_count >= 1)
    )
"""

#: (table, column, DDL type) — every additive provider-identity column.
_NEW_COLUMNS = [
    ("leagues",  "provider",             "VARCHAR"),
    ("leagues",  "provider_league_key",  "VARCHAR"),
    ("teams",    "provider",             "VARCHAR"),
    ("teams",    "provider_team_key",    "VARCHAR"),
    ("teams",    "provider_team_id",     "INTEGER"),
    ("players",  "provider",             "VARCHAR"),
    ("players",  "provider_player_key",  "VARCHAR"),
    ("matchups", "provider_matchup_key", "VARCHAR"),
]

#: Constraints S6-R1 requires be REMOVED. Postgres names a column-level UNIQUE
#: "<table>_<column>_key" by default, but a table created through SQLAlchemy's
#: create_all may carry a different generated name, so each is looked up by the
#: columns it covers rather than by an assumed name.
_DROP_UNIQUES = [
    ("teams",   "email"),
    ("players", "name"),
    ("players", "yahoo_id"),
]

_NEW_INDEXES = [
    ("ix_teams_email",      "teams",   "(email)"),
    ("ix_players_name",     "players", "(name)"),
    ("ix_players_yahoo_id", "players", "(yahoo_id)"),
]

_NEW_UNIQUES = [
    ("uq_leagues_provider_key",          "leagues",
     "(provider, provider_league_key)"),
    ("uq_teams_provider_key",            "teams",
     "(provider, provider_team_key)"),
    ("uq_teams_league_provider_key",     "teams",
     "(league_id, provider_team_key)"),
    ("uq_players_provider_key",          "players",
     "(provider, provider_player_key)"),
    ("uq_matchups_provider_key",         "matchups",
     "(league_id, provider_matchup_key)"),
    # §5 — the mirrored-pair backstop. LEAST/GREATEST is the PostgreSQL spelling
    # of the same constraint db/schema.py emits for SQLite with MIN/MAX.
    ("uq_matchups_unordered_pair",       "matchups",
     "(league_id, week, LEAST(home_team_id, away_team_id), "
     "GREATEST(home_team_id, away_team_id))"),
]


def _table_exists(conn, table: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema='public' AND table_name=:t)
    """), {"t": table}).scalar()


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema='public'
                         AND table_name=:t AND column_name=:c)
    """), {"t": table, "c": column}).scalar()


def _single_column_unique_constraints(conn, table: str, column: str) -> list[str]:
    """Names of UNIQUE constraints on `table` covering EXACTLY `column`.

    Exactly-one-column matters: a composite UNIQUE that happens to include this
    column is a different statement and must not be collateral damage.
    """
    rows = conn.execute(text("""
        SELECT tc.constraint_name
          FROM information_schema.table_constraints tc
          JOIN information_schema.key_column_usage kcu
            ON kcu.constraint_name = tc.constraint_name
           AND kcu.table_schema    = tc.table_schema
         WHERE tc.table_schema    = 'public'
           AND tc.table_name      = :t
           AND tc.constraint_type = 'UNIQUE'
         GROUP BY tc.constraint_name
        HAVING COUNT(*) = 1
           AND MIN(kcu.column_name) = :c
    """), {"t": table, "c": column}).fetchall()
    return [r[0] for r in rows]


def _index_exists(conn, name: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (SELECT 1 FROM pg_indexes
                       WHERE schemaname='public' AND indexname=:n)
    """), {"n": name}).scalar()


def _preflight(conn) -> None:
    """Refuse, whole, if live data would violate a UNIQUE this migration adds.

    Runs AFTER the columns exist (so the queries parse) and BEFORE any UNIQUE is
    created. Every new key column is NULL at this point for existing rows, and
    NULLs are distinct under a UNIQUE, so a clean database has nothing to report
    — but a re-run against a partially-populated database would, and that is
    precisely the case worth catching before the constraint slams shut.
    """
    checks = [
        ("leagues",  "provider, provider_league_key",  "provider_league_key"),
        ("teams",    "provider, provider_team_key",    "provider_team_key"),
        ("teams",    "league_id, provider_team_key",   "provider_team_key"),
        ("players",  "provider, provider_player_key",  "provider_player_key"),
        ("matchups", "league_id, provider_matchup_key", "provider_matchup_key"),
    ]
    for table, cols, notnull in checks:
        dupes = conn.execute(text(
            f"SELECT {cols}, COUNT(*) FROM {table} "
            f"WHERE {notnull} IS NOT NULL "
            f"GROUP BY {cols} HAVING COUNT(*) > 1")).fetchall()
        if dupes:
            raise RuntimeError(
                f"pre-flight refused: {table} already holds duplicate "
                f"({cols}) values {dupes!r}. Two rows claiming one provider "
                f"identity is the conflicting-identity case S6-R1 fails closed "
                f"on; resolve it by hand rather than letting a migration pick "
                f"a winner.")

    mirrored = conn.execute(text(
        "SELECT league_id, week, LEAST(home_team_id, away_team_id), "
        "       GREATEST(home_team_id, away_team_id), COUNT(*) "
        "  FROM matchups "
        " GROUP BY 1,2,3,4 HAVING COUNT(*) > 1")).fetchall()
    if mirrored:
        raise RuntimeError(
            f"pre-flight refused: matchups already holds mirrored duplicate "
            f"pairs {mirrored!r}. Sprint 6 §5 requires one provider matchup to "
            f"be one row; deleting the duplicate is a data decision with "
            f"downstream settlement consequences and is not this migration's "
            f"to make.")


def upgrade(engine) -> None:
    with engine.begin() as conn:
        # 1 — additive identity columns, first, so pre-flight can query them.
        for table, column, ddl_type in _NEW_COLUMNS:
            if not _column_exists(conn, table, column):
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
                print(f"  {table}.{column} added")

        _preflight(conn)

        # 2/3/4 — drop the three inappropriate identity constraints.
        for table, column in _DROP_UNIQUES:
            for name in _single_column_unique_constraints(conn, table, column):
                conn.execute(text(
                    f'ALTER TABLE {table} DROP CONSTRAINT "{name}"'))
                print(f"  {table}.{column} UNIQUE dropped ({name})")

        for name, table, cols in _NEW_INDEXES:
            if not _index_exists(conn, name):
                conn.execute(text(
                    f"CREATE INDEX {name} ON {table} {cols}"))
                print(f"  {name} created")

        # 1b/5 — the scoped UNIQUEs that replace them, plus the pair backstop.
        for name, table, cols in _NEW_UNIQUES:
            if not _index_exists(conn, name):
                conn.execute(text(
                    f"CREATE UNIQUE INDEX {name} ON {table} {cols}"))
                print(f"  {name} created")

        # 5 — the conflict record.
        if not _table_exists(conn, "provider_conflict"):
            conn.execute(text(_CREATE_PROVIDER_CONFLICT))
            conn.execute(text(
                "CREATE INDEX ix_provider_conflict_open "
                "ON provider_conflict (league_id, resolved_at)"))
            print("  provider_conflict created")

    with engine.connect() as conn:
        if not _table_exists(conn, "provider_conflict"):
            raise RuntimeError("verification failed -- provider_conflict absent")
        for name, _table, _cols in _NEW_UNIQUES:
            if not _index_exists(conn, name):
                raise RuntimeError(f"verification failed -- {name} absent")
        for table, column in _DROP_UNIQUES:
            if _single_column_unique_constraints(conn, table, column):
                raise RuntimeError(
                    f"verification failed -- {table}.{column} is still UNIQUE")
    print("\n  MIGRATION COMPLETE.")


def downgrade(engine) -> None:
    """Drop what this migration created. Does NOT restore the three dropped
    UNIQUEs: by the time a downgrade runs, data may legitimately exist that
    violates them (a same-name player, one manager in two leagues), and
    recreating the constraint would fail or, worse, force a data deletion to
    satisfy a constraint S6-R1 ruled invalid. NOT auto-invoked."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS provider_conflict CASCADE"))
        for name, _table, _cols in _NEW_UNIQUES:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        for name, _table, _cols in _NEW_INDEXES:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        for table, column, _ddl in _NEW_COLUMNS:
            conn.execute(text(
                f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}"))
    print("  DOWNGRADE COMPLETE.")


if __name__ == "__main__":
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    print("\nmigrate_s6_provider_gateway.py  --  Sprint 6 provider schema\n")
    from db.schema import engine  # noqa: E402

    db_url = str(engine.url)
    if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
        print("!! ERROR: Postgres target not detected.")
        sys.exit(1)
    try:
        upgrade(engine)
    except Exception as exc:  # noqa: BLE001
        print(f"\n!! ERROR: migration failed and rolled back: {exc}")
        sys.exit(1)
