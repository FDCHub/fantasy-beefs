#!/usr/bin/env python3
"""
migrate_pool_rotation_tables.py  —  Production schema migration creating the
three Weekly Pool Rotation tables: pool_definition (§C1), pool_instance (§C2)
and pool_rotation_cycle (§C3).

Product authority : spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_0.md
Implementation    : spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_0.md

WHY ONE MIGRATION FOR THREE TABLES. This repo has no migration runner, no
version table, and no ordering mechanism of any kind — migrations are individual
scripts a human runs by hand. pool_instance carries a foreign key to
pool_definition, so creation order is load-bearing; three separate files would
put that ordering in a human's memory with nothing enforcing it. One file, one
engine.begin() transaction, correct order internally, all-or-nothing.

CALLABLE ENTRY POINT. upgrade(engine) takes the engine as a parameter rather
than importing a process-wide one, so a test can call the REAL migration against
a disposable local database instead of duplicating this DDL. A duplicated copy
in a test proves only that the copy works — it drifts from production silently,
which is the exact failure the test exists to prevent. The production DDL lives
in exactly one place: the module constants below.

SAFE:
  - Additive only. Creates three new tables; never drops or alters an existing
    table or column, and never touches pool_config, pool_pots, pool_predictions
    or pool_bet_picks.
  - Idempotent: each table's existence is checked against information_schema
    BEFORE its CREATE. Already-present tables are skipped, so a re-run is a
    clean no-op and a partially applied state can be completed.
  - One transaction (engine.begin()). Postgres DDL is fully transactional, so a
    failure anywhere rolls the whole set back — never a half-created schema.
  - Postgres-only, matching the existing migration convention.

WHAT THIS MIGRATION DOES NOT DO. It does not seed catalog rows, does not wire
collection or settlement, and writes nothing to pot_cents or rollover_cents.
Creating a money-bearing column is schema work; writing one is money-path work.

USAGE:
  python db/migrations/migrate_pool_rotation_tables.py
  # or, from a test:  from db.migrations.migrate_pool_rotation_tables import upgrade
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

# ── The partial-index predicate: ONE definition, used to build the DDL ────────
# Bound once here and interpolated into the CREATE UNIQUE INDEX below so the
# migration cannot drift from itself. It must stay character-identical to the
# sqlite_where/postgresql_where text on PoolInstance in db/schema.py — enforcement
# was proven under exactly this predicate on SQLite 3.50.4 and PostgreSQL 16.14.
_PARTIAL_PREDICATE = "origin_instance_id IS NULL AND phase = 'REGULAR'"

_TABLES = ("pool_definition", "pool_instance", "pool_rotation_cycle")

_CREATE_POOL_DEFINITION = """
    CREATE TABLE pool_definition (
        key                                VARCHAR PRIMARY KEY,
        catalog_number                     INTEGER NOT NULL,
        display_name                       VARCHAR NOT NULL,
        category                           VARCHAR NOT NULL,
        scope                              VARCHAR NOT NULL,
        mechanic                           VARCHAR NOT NULL,
        evaluator_family                   VARCHAR NOT NULL,
        metric_kind                        VARCHAR NOT NULL,
        direction                          VARCHAR,
        metric_expression                  VARCHAR,
        threshold_condition                VARCHAR,
        threshold_configurable             BOOLEAN NOT NULL,
        self_pick_rule                     VARCHAR NOT NULL,
        anti_tanking_review                VARCHAR NOT NULL,
        data_dependency                    VARCHAR NOT NULL,
        dependency_state                   VARCHAR NOT NULL,
        block_reason                       VARCHAR,
        regular_season_eligible            BOOLEAN NOT NULL,
        postseason_eligible                BOOLEAN,
        rollover_eligible                  BOOLEAN NOT NULL,
        tie_rule                           VARCHAR NOT NULL,
        aggregate_over_aggregate_required  BOOLEAN NOT NULL,
        zero_denominator_guard             BOOLEAN NOT NULL,
        CONSTRAINT ck_pool_definition_scope
            CHECK (scope IN ('TEAM','MATCHUP')),
        CONSTRAINT ck_pool_definition_mechanic
            CHECK (mechanic IN ('PREDICTION','RANK')),
        CONSTRAINT ck_pool_definition_evaluator_family
            CHECK (evaluator_family IN ('RANK_EXTREMUM','QUALIFIER')),
        CONSTRAINT ck_pool_definition_metric_kind
            CHECK (metric_kind IN ('SIMPLE_AGG','RATIO','COMPOSITE')),
        CONSTRAINT ck_pool_definition_direction
            CHECK (direction IS NULL OR direction IN ('MAX','MIN')),
        CONSTRAINT ck_pool_definition_dependency_state
            CHECK (dependency_state IN ('ENABLED','BLOCKED'))
    )
"""

_CREATE_POOL_INSTANCE = """
    CREATE TABLE pool_instance (
        id                  SERIAL PRIMARY KEY,
        league_id           INTEGER NOT NULL REFERENCES leagues(id),
        season              INTEGER NOT NULL,
        week                INTEGER NOT NULL,
        phase               VARCHAR NOT NULL,
        rotation_cycle      INTEGER NOT NULL,
        definition_key      VARCHAR NOT NULL REFERENCES pool_definition(key),
        slot                INTEGER NOT NULL,
        pot_cents           BIGINT  NOT NULL DEFAULT 0,
        rollover_cents      BIGINT  NOT NULL DEFAULT 0,
        origin_instance_id  INTEGER CONSTRAINT fk_pool_instance_origin
                                    REFERENCES pool_instance(id),
        settled             BOOLEAN NOT NULL DEFAULT FALSE,
        settled_at          TIMESTAMPTZ,
        CONSTRAINT ck_pool_instance_phase
            CHECK (phase IN ('REGULAR','POSTSEASON')),
        CONSTRAINT ck_pool_instance_slot
            CHECK (slot BETWEEN 1 AND 4),
        CONSTRAINT uq_pool_instance_week_definition
            UNIQUE (league_id, season, week, definition_key),
        CONSTRAINT uq_pool_instance_week_slot
            UNIQUE (league_id, season, week, slot)
    )
"""

# Built from _PARTIAL_PREDICATE so the predicate exists once in this file.
_CREATE_POOL_INSTANCE_PARTIAL_INDEX = f"""
    CREATE UNIQUE INDEX uq_pool_instance_cycle_fresh
        ON pool_instance (league_id, season, rotation_cycle, definition_key)
        WHERE {_PARTIAL_PREDICATE}
"""

_CREATE_POOL_ROTATION_CYCLE = """
    CREATE TABLE pool_rotation_cycle (
        id                 SERIAL PRIMARY KEY,
        league_id          INTEGER NOT NULL REFERENCES leagues(id),
        season             INTEGER NOT NULL,
        rotation_cycle     INTEGER NOT NULL,
        opened_week        INTEGER NOT NULL,
        eligible_set_size  INTEGER NOT NULL,
        opened_at          TIMESTAMPTZ,
        CONSTRAINT uq_pool_rotation_cycle_open
            UNIQUE (league_id, season, rotation_cycle)
    )
"""


def _table_exists(conn, table: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = :t
        )
    """), {"t": table}).scalar()


def upgrade(engine) -> None:
    """Create the three Pool rotation tables on `engine`, in dependency order.

    Idempotent per table: an already-present table is skipped, so re-running is
    a clean no-op and a partially applied state completes. Everything runs in a
    single transaction — a failure rolls back all three.
    """
    with engine.connect() as conn:
        present = {t: _table_exists(conn, t) for t in _TABLES}

    for t in _TABLES:
        print(f"  {t:22s} exists : {present[t]}")

    if all(present.values()):
        print("\n  all three tables already exist -- nothing to do.")
        return

    with engine.begin() as conn:
        # Order is load-bearing: pool_instance references pool_definition(key).
        if not present["pool_definition"]:
            conn.execute(text(_CREATE_POOL_DEFINITION))
            print("  pool_definition created")
        if not present["pool_instance"]:
            conn.execute(text(_CREATE_POOL_INSTANCE))
            conn.execute(text(_CREATE_POOL_INSTANCE_PARTIAL_INDEX))
            print("  pool_instance created (+ uq_pool_instance_cycle_fresh)")
        if not present["pool_rotation_cycle"]:
            conn.execute(text(_CREATE_POOL_ROTATION_CYCLE))
            print("  pool_rotation_cycle created")

    with engine.connect() as conn:
        after = {t: _table_exists(conn, t) for t in _TABLES}
    missing = [t for t, ok in after.items() if not ok]
    if missing:
        raise RuntimeError(
            f"migration verification failed -- still missing: {missing}"
        )
    print("\n  MIGRATION COMPLETE.")


def downgrade(engine) -> None:
    """Reverse this migration: DROP the three tables, children first. NOT
    auto-invoked. Idempotent, single transaction, touches nothing else."""
    with engine.begin() as conn:
        for t in ("pool_rotation_cycle", "pool_instance", "pool_definition"):
            conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
            print(f"  {t} dropped (if present)")
    print("  DOWNGRADE COMPLETE.")


if __name__ == "__main__":
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    print("\nmigrate_pool_rotation_tables.py  --  Pool rotation schema migration\n")

    from db.schema import engine  # noqa: E402  (import deferred: __main__ only)

    db_url = str(engine.url)
    if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
        print("!! ERROR: Postgres target not detected.")
        print("   DATABASE_URL is missing or does not point at a Postgres instance.")
        sys.exit(1)

    print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")
    try:
        upgrade(engine)
    except Exception as exc:  # noqa: BLE001
        print(f"\n!! ERROR: migration failed and the transaction rolled back: {exc}")
        sys.exit(1)
