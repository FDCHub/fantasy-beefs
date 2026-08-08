#!/usr/bin/env python3
"""
migrate_s4_common_pool_engine.py — S4-P1 schema for the common Pool engine.

Product authority : spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_3.md
Implementation    : spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_3.md

RUNS AFTER migrate_pool_rotation_tables.py, WHICH IT EXTENDS RATHER THAN
REPLACES. That migration created pool_definition/pool_instance/
pool_rotation_cycle against Revision 1.0. Revision 1.3 widened the catalog field
set, renamed one column, and added the claim, economic-event and gate-2 carrier
tables. Everything here is applied on top; nothing it created is dropped.

SAFE:
  - Additive except for ONE rename (block_reason -> blocked_reason), which
    preserves values byte-for-byte. POR §7.0 makes blocked_reason the single
    canonical field, and keeping both would leave two fields free to disagree.
  - Idempotent. Every step checks information_schema first, so a re-run is a
    clean no-op and a partially applied state completes.
  - One transaction. Postgres DDL is fully transactional, so a failure anywhere
    rolls the whole set back — never a half-migrated schema.
  - Postgres-only, matching the existing migration convention.

WHY NOT NULL IS APPLIED CONDITIONALLY ON pool_definition. Seven Rev1.3 columns
are NOT NULL in db/schema.py because every one of the 80 governed rows carries
them. `ADD COLUMN ... NOT NULL` against a NON-EMPTY table fails without a
DEFAULT, and there is no honest default for `evaluator_shape` on a row this
migration did not write. So: the columns are added NULLABLE, and NOT NULL is
applied only once every row satisfies it — which is automatic on the expected
empty table, and achieved by re-seeding otherwise. If a row still holds NULL
afterwards the migration REPORTS it precisely and leaves the column nullable
rather than deleting the row or inventing a value. Losing a row would violate
§15's "do not casually drop old data"; inventing a shape would be worse.

WHAT THIS MIGRATION DOES NOT DO. It seeds no catalog rows, wires no collection
or settlement, and moves no money. Creating a money-bearing column is schema
work; writing one is money-path work — see migrate_s4_pool_rollover_money.py.

USAGE:
  python db/migrations/migrate_s4_common_pool_engine.py
  # or, from a test:  from db.migrations.migrate_s4_common_pool_engine import upgrade
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import text

# ── New columns, per table ────────────────────────────────────────────────────
#
# (column, type, nullable-at-add). Ordered as db/schema.py declares them so the
# two files read the same way when compared side by side.

_LEAGUE_COLUMNS = [
    ("season_final_week", "INTEGER", True),
    ("playoff_start_week", "INTEGER", True),
]

_POOL_CONFIG_COLUMNS = [
    ("pool_weekly_entry_cents", "INTEGER", True),
    ("pool_weekly_entry_frozen_at", "TIMESTAMPTZ", True),
]

_POOL_INSTANCE_COLUMNS = [
    ("settlement_classification", "VARCHAR", True),
    ("distributed_cents", "BIGINT NOT NULL DEFAULT 0", False),
]

# Added nullable; tightened below where the data permits.
_POOL_DEFINITION_COLUMNS = [
    ("evaluator_shape", "VARCHAR", True),
    ("governed_definition", "VARCHAR", True),
    ("predicate", "VARCHAR", True),
    ("predicate_quantifier", "VARCHAR", True),
    ("threshold_default", "INTEGER", True),
    ("required_stats", "JSON", True),
    ("required_stats_resolved", "BOOLEAN", True),
    ("required_stats_unresolved_reason", "VARCHAR", True),
    ("source_mapping_complete", "BOOLEAN", True),
    ("unmapped_required_stats", "JSON", True),
    ("starter_slot_rule", "VARCHAR", True),
    ("slot_filter", "JSON", True),
    ("slot_exclusions", "JSON", True),
    ("product_complete", "BOOLEAN", True),
    ("definition_runtime_eligible", "BOOLEAN", True),
    ("definition_block_reason", "VARCHAR", True),
]

#: Columns db/schema.py declares NOT NULL. Tightened only when no row violates.
_POOL_DEFINITION_NOT_NULL = (
    "evaluator_shape", "required_stats_resolved", "source_mapping_complete",
    "starter_slot_rule", "product_complete", "definition_runtime_eligible",
)

_POOL_DEFINITION_CONSTRAINTS = [
    ("ck_pool_definition_metric_kind_v13",
     "CHECK (metric_kind IN ('SIMPLE_AGG','RATIO','COMPOSITE','PLAYER_EXTREMUM',"
     "'POINTS_AGG','BALANCE_RATIO','CATEGORY_COUNT'))"),
    ("ck_pool_definition_evaluator_shape",
     "CHECK (evaluator_shape IS NULL OR evaluator_shape IN "
     "('CLOSED_SUM','CLOSED_RATIO','QUALIFIER_PREDICATE',"
     "'PLAYER_EXTREMUM_WITHIN_SUBJECT','SLOT_FILTERED_POINTS_SUM',"
     "'BALANCE_RATIO','DISTINCT_CATEGORY_COUNT','MATCHUP_SCORE_SUM'))"),
    ("ck_pool_definition_predicate_quantifier",
     "CHECK (predicate_quantifier IS NULL OR predicate_quantifier IN "
     "('TEAM','MATCHUP_COMBINED','MATCHUP_EACH'))"),
    ("ck_pool_definition_blocked_reason",
     "CHECK ((dependency_state = 'BLOCKED' AND blocked_reason IS NOT NULL) OR "
     "(dependency_state = 'ENABLED' AND blocked_reason IS NULL))"),
    # POR §1.1 / conformance 34e, 40 — retired numbers are reserved permanently.
    # Enforced at the database so no fixture, manual INSERT or future migration
    # can resurrect one; the seeder's own refusal is the second, independent
    # guard, because a seeder can be bypassed and a CHECK cannot.
    ("ck_pool_definition_retired_numbers",
     "CHECK (catalog_number NOT IN (8, 9, 10, 11, 12, 44, 45, 47, 50, 51, 52, "
     "57, 81, 82, 88, 96, 97, 98))"),
]

_CREATE_POOL_LEAGUE_ACTIVATION = """
    CREATE TABLE pool_league_activation (
        id                              SERIAL PRIMARY KEY,
        league_id                       INTEGER NOT NULL REFERENCES leagues(id),
        provider                        VARCHAR NOT NULL,
        definition_key                  VARCHAR NOT NULL
                                        REFERENCES pool_definition(key),
        league_activation_ready         BOOLEAN NOT NULL,
        league_activation_block_reasons JSON,
        measured_at                     TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_pool_league_activation_scope
            UNIQUE (league_id, provider, definition_key)
    )
"""

_CREATE_POOL_CLAIM = """
    CREATE TABLE pool_claim (
        id                    SERIAL PRIMARY KEY,
        pool_instance_id      INTEGER NOT NULL REFERENCES pool_instance(id),
        league_id             INTEGER NOT NULL REFERENCES leagues(id),
        team_id               INTEGER NOT NULL REFERENCES teams(id),
        selected_subject_type VARCHAR NOT NULL,
        selected_subject_id   INTEGER NOT NULL,
        submitted_at          TIMESTAMPTZ NOT NULL,
        CONSTRAINT ck_pool_claim_subject_type
            CHECK (selected_subject_type IN ('TEAM','MATCHUP')),
        CONSTRAINT uq_pool_claim_instance_gm
            UNIQUE (pool_instance_id, team_id)
    )
"""

_CREATE_POOL_ECONOMIC_EVENT = """
    CREATE TABLE pool_economic_event (
        id               SERIAL PRIMARY KEY,
        league_id        INTEGER NOT NULL REFERENCES leagues(id),
        season           INTEGER NOT NULL,
        week             INTEGER NOT NULL,
        pool_instance_id INTEGER REFERENCES pool_instance(id),
        event_type       VARCHAR NOT NULL,
        posting_id       UUID,
        amount_cents     BIGINT NOT NULL,
        created_at       TIMESTAMPTZ NOT NULL,
        CONSTRAINT ck_pool_economic_event_type CHECK (event_type IN (
            'WEEKLY_COLLECTION',
            'WEEKLY_DIVISION_REMAINDER',
            'WINNER_DISTRIBUTION',
            'SUBJECT_ZERO_CLAIM_ROLLOVER',
            'SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP',
            'TICKET_ZERO_WINNER_ROLLOVER',
            'TICKET_ZERO_WINNER_CHAMPIONSHIP_SWEEP',
            'ROLLOVER_EXPIRY_SWEEP')),
        CONSTRAINT ck_pool_economic_event_amount_nonneg
            CHECK (amount_cents >= 0)
    )
"""

# TWO PARTIAL UNIQUE INDEXES, NOT ONE COMBINED CONSTRAINT. §G1's conceptual key
# is (pool_instance_id, economic_event_type), but weekly collection and the
# division remainder are WEEK-level causes with no owning instance. NULLs are
# distinct in a UNIQUE index on both backends, so a single combined constraint
# would let every replayed weekly collection insert a fresh row and the guard
# would be silently inert. Each shape gets its own index, each covering exactly
# the rows it governs.
_CREATE_EVENT_INDEXES = (
    """
    CREATE UNIQUE INDEX uq_pool_economic_event_instance
        ON pool_economic_event (pool_instance_id, event_type)
        WHERE pool_instance_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX uq_pool_economic_event_week
        ON pool_economic_event (league_id, season, week, event_type)
        WHERE pool_instance_id IS NULL
    """,
)

_CREATE_POOL_LEGACY_ROLLOVER_MIGRATION = """
    CREATE TABLE pool_legacy_rollover_migration (
        id                  SERIAL PRIMARY KEY,
        migration_key       VARCHAR NOT NULL,
        league_id           INTEGER NOT NULL REFERENCES leagues(id),
        source_field        VARCHAR NOT NULL,
        source_weeks        JSON NOT NULL,
        amount_cents        BIGINT NOT NULL,
        destination_account VARCHAR NOT NULL,
        posting_id          UUID NOT NULL,
        migrated_at         TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_pool_legacy_rollover_migration_key
            UNIQUE (migration_key),
        CONSTRAINT ck_pool_legacy_rollover_amount_positive
            CHECK (amount_cents > 0)
    )
"""

_NEW_TABLES = ("pool_league_activation", "pool_claim", "pool_economic_event",
               "pool_legacy_rollover_migration")


# ── introspection helpers ─────────────────────────────────────────────────────

def _table_exists(conn, table: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema = 'public' AND table_name = :t)
    """), {"t": table}).scalar()


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public'
                         AND table_name = :t AND column_name = :c)
    """), {"t": table, "c": column}).scalar()


def _constraint_exists(conn, table: str, name: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.table_constraints
                       WHERE table_schema = 'public'
                         AND table_name = :t AND constraint_name = :n)
    """), {"t": table, "n": name}).scalar()


def _index_exists(conn, name: str) -> bool:
    return conn.execute(text("""
        SELECT EXISTS (SELECT 1 FROM pg_indexes
                       WHERE schemaname = 'public' AND indexname = :n)
    """), {"n": name}).scalar()


def _add_columns(conn, table: str, columns) -> None:
    for name, ddl_type, _nullable in columns:
        if _column_exists(conn, table, name):
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))
        print(f"  {table}.{name} added")


def upgrade(engine) -> None:
    """Apply the S4-P1 schema to `engine`. Idempotent, one transaction."""
    with engine.begin() as conn:
        if not _table_exists(conn, "pool_definition"):
            raise RuntimeError(
                "pool_definition is absent — run "
                "db/migrations/migrate_pool_rotation_tables.py first. This "
                "migration extends the Rev1.0 rotation schema; it does not "
                "recreate it."
            )

        # ── 1. rename block_reason -> blocked_reason (POR §7.0) ─────────────
        has_old = _column_exists(conn, "pool_definition", "block_reason")
        has_new = _column_exists(conn, "pool_definition", "blocked_reason")
        if has_old and not has_new:
            conn.execute(text(
                "ALTER TABLE pool_definition "
                "RENAME COLUMN block_reason TO blocked_reason"))
            print("  pool_definition.block_reason -> blocked_reason (renamed)")
        elif has_old and has_new:
            # Two live fields for one fact. Refusing beats guessing which one an
            # earlier partial run left authoritative.
            raise RuntimeError(
                "pool_definition carries BOTH block_reason and blocked_reason. "
                "POR §7.0 admits one canonical field. Resolve manually — this "
                "migration will not choose between two populated columns."
            )

        # ── 2. new columns ──────────────────────────────────────────────────
        _add_columns(conn, "leagues", _LEAGUE_COLUMNS)
        _add_columns(conn, "pool_config", _POOL_CONFIG_COLUMNS)
        _add_columns(conn, "pool_instance", _POOL_INSTANCE_COLUMNS)
        _add_columns(conn, "pool_definition", _POOL_DEFINITION_COLUMNS)

        # ── 3. constraints ──────────────────────────────────────────────────
        if not _constraint_exists(conn, "pool_config",
                                  "ck_pool_config_weekly_entry_bounds"):
            # NULL passes: an unconfigured league reads the governed §6.1
            # default through betting/pool_funding.py rather than carrying it.
            conn.execute(text(
                "ALTER TABLE pool_config ADD CONSTRAINT "
                "ck_pool_config_weekly_entry_bounds CHECK ("
                "pool_weekly_entry_cents IS NULL OR "
                "(pool_weekly_entry_cents >= 100 AND "
                " pool_weekly_entry_cents <= 500))"))
            print("  pool_config §6.1 bound constraint added")

        # The Rev1.0 metric_kind CHECK admits only three values; Rev1.3 carries
        # seven. Dropped and replaced under a NEW name so a re-run is
        # unambiguous about which revision's constraint is present.
        if _constraint_exists(conn, "pool_definition",
                              "ck_pool_definition_metric_kind"):
            conn.execute(text("ALTER TABLE pool_definition DROP CONSTRAINT "
                              "ck_pool_definition_metric_kind"))
            print("  Rev1.0 metric_kind CHECK dropped")
        for name, ddl in _POOL_DEFINITION_CONSTRAINTS:
            if _constraint_exists(conn, "pool_definition", name):
                continue
            conn.execute(text(
                f"ALTER TABLE pool_definition ADD CONSTRAINT {name} {ddl}"))
            print(f"  pool_definition {name} added")

        # ── 4. new tables ───────────────────────────────────────────────────
        if not _table_exists(conn, "pool_league_activation"):
            conn.execute(text(_CREATE_POOL_LEAGUE_ACTIVATION))
            print("  pool_league_activation created")
        if not _table_exists(conn, "pool_claim"):
            conn.execute(text(_CREATE_POOL_CLAIM))
            print("  pool_claim created")
        if not _table_exists(conn, "pool_economic_event"):
            conn.execute(text(_CREATE_POOL_ECONOMIC_EVENT))
            print("  pool_economic_event created")
        if not _table_exists(conn, "pool_legacy_rollover_migration"):
            # The audit carrier for the 2026-08-08 owner ruling on the legacy
            # Worst Beat carry. Created as SCHEMA work here; the balance itself
            # is moved by migrate_s4_pool_rollover_money.py, which is money-path
            # work behind its own gate.
            conn.execute(text(_CREATE_POOL_LEGACY_ROLLOVER_MIGRATION))
            print("  pool_legacy_rollover_migration created")
        for ddl in _CREATE_EVENT_INDEXES:
            index_name = ddl.split("CREATE UNIQUE INDEX")[1].split()[0].strip()
            if not _index_exists(conn, index_name):
                conn.execute(text(ddl))
                print(f"  {index_name} created")

        # ── 5. tighten NOT NULL where the data already permits ──────────────
        rows = conn.execute(text("SELECT count(*) FROM pool_definition")).scalar()
        still_nullable: list[str] = []
        for column in _POOL_DEFINITION_NOT_NULL:
            nulls = conn.execute(text(
                f"SELECT count(*) FROM pool_definition "
                f"WHERE {column} IS NULL")).scalar()
            if nulls:
                still_nullable.append(f"{column} ({nulls} NULL of {rows})")
                continue
            conn.execute(text(
                f"ALTER TABLE pool_definition "
                f"ALTER COLUMN {column} SET NOT NULL"))
        if still_nullable:
            # REPORTED, NOT PAPERED OVER. The remedy is to run
            # betting.pool_catalog.seed_definitions and re-run this migration;
            # deleting the offending rows or inventing a shape for them would
            # be worse than leaving the column nullable and saying so.
            print("\n  !! NOT NULL deferred on pool_definition columns:")
            for entry in still_nullable:
                print(f"       {entry}")
            print("     Seed the Rev1.3 catalog "
                  "(betting.pool_catalog.seed_definitions), then re-run this "
                  "migration to tighten them.")
        else:
            print(f"  pool_definition NOT NULL applied "
                  f"({len(_POOL_DEFINITION_NOT_NULL)} columns, {rows} rows)")

    # ── verification, outside the DDL transaction ───────────────────────────
    with engine.connect() as conn:
        missing = [t for t in _NEW_TABLES if not _table_exists(conn, t)]
        if missing:
            raise RuntimeError(
                f"migration verification failed -- still missing: {missing}")
        if not _column_exists(conn, "pool_definition", "blocked_reason"):
            raise RuntimeError(
                "migration verification failed -- pool_definition.blocked_reason "
                "absent")
    print("\n  MIGRATION COMPLETE.")


def downgrade(engine) -> None:
    """Reverse this migration: drop the three new tables and the added columns,
    and rename blocked_reason back. NOT auto-invoked.

    Dropping a column DESTROYS its data. This is provided for test teardown and
    for a rollback decision an operator makes deliberately — it is not a
    routine counterpart to upgrade()."""
    with engine.begin() as conn:
        for table in ("pool_claim", "pool_economic_event",
                      "pool_league_activation",
                      "pool_legacy_rollover_migration"):
            conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        for name, _ in _POOL_DEFINITION_CONSTRAINTS:
            conn.execute(text(
                f"ALTER TABLE pool_definition DROP CONSTRAINT IF EXISTS {name}"))
        for column, _t, _n in _POOL_DEFINITION_COLUMNS:
            conn.execute(text(
                f"ALTER TABLE pool_definition DROP COLUMN IF EXISTS {column}"))
        for column, _t, _n in _POOL_INSTANCE_COLUMNS:
            conn.execute(text(
                f"ALTER TABLE pool_instance DROP COLUMN IF EXISTS "
                f"{column.split()[0]}"))
        conn.execute(text("ALTER TABLE pool_config DROP CONSTRAINT IF EXISTS "
                          "ck_pool_config_weekly_entry_bounds"))
        for column, _t, _n in _POOL_CONFIG_COLUMNS:
            conn.execute(text(
                f"ALTER TABLE pool_config DROP COLUMN IF EXISTS {column}"))
        for column, _t, _n in _LEAGUE_COLUMNS:
            conn.execute(text(
                f"ALTER TABLE leagues DROP COLUMN IF EXISTS {column}"))
        if _column_exists(conn, "pool_definition", "blocked_reason") \
                and not _column_exists(conn, "pool_definition", "block_reason"):
            conn.execute(text("ALTER TABLE pool_definition "
                              "RENAME COLUMN blocked_reason TO block_reason"))
    print("  DOWNGRADE COMPLETE.")


if __name__ == "__main__":
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    print("\nmigrate_s4_common_pool_engine.py  --  S4-P1 Pool schema\n")

    from db.schema import engine  # noqa: E402  (deferred: __main__ only)

    db_url = str(engine.url)
    if not os.environ.get("DATABASE_URL") or "postgres" not in db_url:
        print("!! ERROR: Postgres target not detected.")
        print("   DATABASE_URL is missing or does not point at a Postgres "
              "instance.")
        sys.exit(1)

    print(f"  target : {db_url.split('@')[-1] if '@' in db_url else db_url}\n")
    try:
        upgrade(engine)
    except Exception as exc:  # noqa: BLE001
        print(f"\n!! ERROR: migration failed and the transaction rolled back: "
              f"{exc}")
        sys.exit(1)